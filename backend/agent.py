"""
ScreenPilotAgent — built with Google Agent Development Kit (ADK).

The agent owns the session state and runs the perception→plan→act loop.
Each iteration:
  1. Receives a screenshot from the frontend
  2. Calls GeminiClient.analyze_screen() to get the next action
  3. Emits the action back to the frontend via callback
  4. Waits for the action result (success / failure)
  5. Repeats until done or max_steps reached
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import AsyncGenerator, Callable, Optional

from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions

from action_models import (
    AgentAction,
    AskUserAction,
    DoneAction,
    ScreenshotAction,
    ServerMessage,
)
from gemini_client import GeminiClient

logger = logging.getLogger(__name__)

MAX_STEPS = 50          # hard cap per session
SCREENSHOT_TIMEOUT = 10  # seconds to wait for a screenshot from client


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class AgentSession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    goal: str = ""
    history: list[dict] = field(default_factory=list)
    step: int = 0
    done: bool = False
    waiting_for_screenshot: bool = False
    last_screenshot_b64: Optional[str] = None
    screen_width: int = 1280
    screen_height: int = 720
    # asyncio events for synchronisation
    screenshot_ready: asyncio.Event = field(default_factory=asyncio.Event)
    action_result_ready: asyncio.Event = field(default_factory=asyncio.Event)
    last_action_success: bool = True
    last_action_error: Optional[str] = None


# ---------------------------------------------------------------------------
# ScreenPilotAgent (ADK BaseAgent subclass)
# ---------------------------------------------------------------------------

class ScreenPilotAgent(BaseAgent):
    """
    Multimodal UI navigation agent powered by Gemini 2.0 Flash.

    Usage:
        agent = ScreenPilotAgent()
        async for event in agent.run_session(session, send_fn):
            ...
    """

    name = "ScreenPilotAgent"
    description = "Observes a browser screen and executes actions to complete user goals."

    def __init__(self) -> None:
        super().__init__()
        self.gemini = GeminiClient()

    # ------------------------------------------------------------------
    # ADK entry-point
    # ------------------------------------------------------------------

    async def _run_async_impl(
        self,
        ctx,  # google.adk.agents.InvocationContext
    ) -> AsyncGenerator[Event, None]:
        """
        ADK calls this when the agent is invoked.
        We delegate to run_session() which is also exposed directly for
        WebSocket usage without the ADK runner.
        """
        # Extract session from context (attached by the WebSocket handler)
        session: AgentSession = ctx.session.state.get("agent_session")
        send_fn: Callable = ctx.session.state.get("send_fn")

        if session is None or send_fn is None:
            yield Event(
                author=self.name,
                actions=EventActions(escalate=True),
                content="Missing session or send_fn in context state.",
            )
            return

        async for event in self.run_session(session, send_fn):
            yield event

    # ------------------------------------------------------------------
    # Core loop (also callable directly from the WebSocket handler)
    # ------------------------------------------------------------------

    async def run_session(
        self,
        session: AgentSession,
        send_fn: Callable[[ServerMessage], None],
    ) -> AsyncGenerator[Event, None]:
        """
        Main perception → plan → act loop.

        send_fn is called with each ServerMessage to push to the frontend.
        """
        logger.info("[%s] Starting session. Goal: %s", session.session_id, session.goal)

        while session.step < MAX_STEPS and not session.done:
            session.step += 1
            logger.debug("[%s] Step %d", session.session_id, session.step)

            # 1. Request a fresh screenshot
            await send_fn(ServerMessage(
                session_id=session.session_id,
                type="action",
                action=ScreenshotAction(),
            ))

            # 2. Wait for the client to send back the screenshot
            session.screenshot_ready.clear()
            try:
                await asyncio.wait_for(
                    session.screenshot_ready.wait(),
                    timeout=SCREENSHOT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("[%s] Screenshot timeout at step %d", session.session_id, session.step)
                await send_fn(ServerMessage(
                    session_id=session.session_id,
                    type="error",
                    error="Screenshot timeout — did the browser tab close?",
                ))
                break

            image_b64 = session.last_screenshot_b64
            if not image_b64:
                continue

            # 3. Ask Gemini what to do next
            try:
                await send_fn(ServerMessage(
                    session_id=session.session_id,
                    type="status",
                    status="🧠 Analysing screen…",
                ))
                thinking, action_dict = await self.gemini.analyze_screen(
                    image_b64=image_b64,
                    goal=session.goal,
                    history=session.history,
                    screen_width=session.screen_width,
                    screen_height=session.screen_height,
                )
            except Exception as exc:
                logger.exception("[%s] Gemini error", session.session_id)
                await send_fn(ServerMessage(
                    session_id=session.session_id,
                    type="error",
                    error=f"Gemini error: {exc}",
                ))
                break

            # Broadcast thinking narration
            if thinking:
                await send_fn(ServerMessage(
                    session_id=session.session_id,
                    type="thinking",
                    thinking=thinking,
                ))

            # 4. Parse and dispatch the action
            action = self._parse_action(action_dict)
            history_entry = {
                "step": session.step,
                "thinking": thinking,
                "action": action_dict,
                "success": True,
            }

            if isinstance(action, DoneAction):
                session.done = True
                await send_fn(ServerMessage(
                    session_id=session.session_id,
                    type="action",
                    action=action,
                ))
                logger.info("[%s] Done: %s", session.session_id, action.summary)
                session.history.append(history_entry)
                yield Event(
                    author=self.name,
                    content=action.summary,
                )
                return

            if isinstance(action, AskUserAction):
                session.done = True  # pause loop; user must re-trigger
                await send_fn(ServerMessage(
                    session_id=session.session_id,
                    type="action",
                    action=action,
                ))
                session.history.append(history_entry)
                return

            # Regular action — send to frontend and wait for result
            await send_fn(ServerMessage(
                session_id=session.session_id,
                type="action",
                action=action,
            ))

            session.action_result_ready.clear()
            try:
                await asyncio.wait_for(
                    session.action_result_ready.wait(),
                    timeout=15,
                )
            except asyncio.TimeoutError:
                logger.warning("[%s] Action result timeout", session.session_id)

            history_entry["success"] = session.last_action_success
            if not session.last_action_success:
                history_entry["error"] = session.last_action_error
            session.history.append(history_entry)

        if not session.done:
            await send_fn(ServerMessage(
                session_id=session.session_id,
                type="status",
                status=f"⚠️ Reached maximum steps ({MAX_STEPS}). Session ended.",
            ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_action(action_dict: dict) -> AgentAction:
        """Deserialise the action dict returned by Gemini into a typed model."""
        from action_models import (
            ClickAction, RightClickAction, DoubleClickAction, HoverAction,
            TypeAction, ClearAndTypeAction, KeyPressAction, ScrollAction,
            NavigateAction, WaitAction, DoneAction, AskUserAction, ScreenshotAction,
            ActionType,
        )
        action_type = action_dict.get("type", "screenshot")
        mapping = {
            ActionType.CLICK: ClickAction,
            ActionType.RIGHT_CLICK: RightClickAction,
            ActionType.DOUBLE_CLICK: DoubleClickAction,
            ActionType.HOVER: HoverAction,
            ActionType.TYPE: TypeAction,
            ActionType.CLEAR_AND_TYPE: ClearAndTypeAction,
            ActionType.KEY_PRESS: KeyPressAction,
            ActionType.SCROLL: ScrollAction,
            ActionType.NAVIGATE: NavigateAction,
            ActionType.WAIT: WaitAction,
            ActionType.SCREENSHOT: ScreenshotAction,
            ActionType.DONE: DoneAction,
            ActionType.ASK_USER: AskUserAction,
        }
        cls = mapping.get(action_type, ScreenshotAction)
        try:
            return cls(**{k: v for k, v in action_dict.items() if k != "type"})
        except Exception:
            return ScreenshotAction()
