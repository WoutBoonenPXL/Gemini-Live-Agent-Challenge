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
import base64
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import AsyncGenerator, Callable, Optional

from pydantic import PrivateAttr
from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions

from action_models import (
    AgentAction,
    AskUserAction,
    DoneAction,
    ScreenshotAction,
    ServerMessage,
)
from gemini_client import GeminiClient, GeminiRateLimitError
from playwright_driver import PlaywrightDriver

logger = logging.getLogger(__name__)

MAX_STEPS = max(1, int(os.environ.get("AGENT_MAX_STEPS", "1")))
SCREENSHOT_TIMEOUT = 10  # seconds to wait for a screenshot from client
MAX_REPEAT_ACTIONS = 3
MAX_RATE_LIMIT_WAIT_SECONDS = max(1, int(os.environ.get("AGENT_MAX_RATE_LIMIT_WAIT_SECONDS", "8")))
MAX_RATE_LIMIT_RETRIES = max(0, int(os.environ.get("AGENT_MAX_RATE_LIMIT_RETRIES", "1")))


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
    last_screenshot_hash: Optional[str] = None
    last_action_signature: Optional[str] = None
    repeated_action_count: int = 0
    rate_limit_retries: int = 0


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

    _gemini: GeminiClient = PrivateAttr()
    _playwright: PlaywrightDriver = PrivateAttr()

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("name", "ScreenPilotAgent")
        kwargs.setdefault(
            "description",
            "Observes a browser screen and executes actions to complete user goals.",
        )
        super().__init__(**kwargs)
        self._gemini = GeminiClient()
        self._playwright = PlaywrightDriver()

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

        # Launch Playwright browser for this session
        try:
            await self._playwright.launch(headless=True)
        except Exception as exc:
            logger.exception("[%s] Playwright launch failed: %r", session.session_id, exc)
            await send_fn(ServerMessage(
                session_id=session.session_id,
                type="error",
                error=f"Playwright launch failed: {repr(exc)} — make sure you ran 'playwright install' and that the event loop is ProactorEventLoop on Windows.",
            ))
            return
        # If the goal includes a URL, navigate there first
        url_match = re.search(r"https?://\S+", session.goal)
        if url_match:
            await self._playwright.goto(url_match.group(0))

        while session.step < MAX_STEPS and not session.done:
            session.step += 1
            logger.debug("[%s] Step %d", session.session_id, session.step)

            # 1. Capture screenshot directly from Playwright browser
            await send_fn(ServerMessage(
                session_id=session.session_id,
                type="status",
                status="📸 Taking screenshot…",
            ))
            try:
                screenshot_bytes = await self._playwright.screenshot()
                image_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                # Also update viewport size from page
                vp = self._playwright.viewport_size
                if vp:
                    session.screen_width = vp.get("width", 1280)
                    session.screen_height = vp.get("height", 720)
                # Forward screenshot to frontend for display
                await send_fn(ServerMessage(
                    session_id=session.session_id,
                    type="screenshot",
                    image_b64=image_b64,
                ))
            except Exception as exc:
                logger.warning("[%s] Screenshot error: %s", session.session_id, exc)
                await send_fn(ServerMessage(
                    session_id=session.session_id,
                    type="error",
                    error=f"Screenshot failed: {exc}",
                ))
                break

            screenshot_hash = hashlib.sha256(image_b64.encode("utf-8")).hexdigest()

            # 3. Ask Gemini what to do next
            try:
                await send_fn(ServerMessage(
                    session_id=session.session_id,
                    type="status",
                    status="🧠 Analysing screen…",
                ))
                thinking, action_dict = await self._gemini.analyze_screen(
                    image_b64=image_b64,
                    goal=session.goal,
                    history=session.history,
                    screen_width=session.screen_width,
                    screen_height=session.screen_height,
                )
            except GeminiRateLimitError as exc:
                retry_after = min(max(exc.retry_after_seconds, 1.0), 120.0)
                session.rate_limit_retries += 1

                if (
                    retry_after > MAX_RATE_LIMIT_WAIT_SECONDS
                    or session.rate_limit_retries > MAX_RATE_LIMIT_RETRIES
                ):
                    session.done = True
                    await send_fn(ServerMessage(
                        session_id=session.session_id,
                        type="action",
                        action=AskUserAction(
                            question=(
                                "Gemini is currently rate-limited for this key/project. "
                                "Please wait for quota reset or switch credentials, then run again."
                            ),
                            description=(
                                f"Rate limit wait ({retry_after:.1f}s) exceeds threshold "
                                f"({MAX_RATE_LIMIT_WAIT_SECONDS}s)."
                            ),
                        ),
                    ))
                    session.history.append({
                        "step": session.step,
                        "thinking": "Stopped due to Gemini quota/rate limit.",
                        "action": {
                            "type": "ask_user",
                            "question": "Quota/rate limit requires manual retry later.",
                        },
                        "success": False,
                        "error": str(exc),
                    })
                    return

                await send_fn(ServerMessage(
                    session_id=session.session_id,
                    type="status",
                    status=(
                        f"⏳ Gemini rate limit hit. Waiting {retry_after:.1f}s, then retrying…"
                    ),
                ))

                # Don't consume this step when throttled.
                session.step = max(0, session.step - 1)
                await asyncio.sleep(retry_after)
                continue
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
                session.rate_limit_retries = 0
                await send_fn(ServerMessage(
                    session_id=session.session_id,
                    type="thinking",
                    thinking=thinking,
                ))

            # 4. Parse and dispatch the action
            action = self._parse_action(action_dict)
            action_signature = self._action_signature(action_dict)

            if (
                screenshot_hash == session.last_screenshot_hash
                and action_signature == session.last_action_signature
                and action_dict.get("type") not in {"wait", "screenshot", "done", "ask_user"}
            ):
                session.repeated_action_count += 1
            else:
                session.repeated_action_count = 0

            session.last_screenshot_hash = screenshot_hash
            session.last_action_signature = action_signature

            if session.repeated_action_count >= MAX_REPEAT_ACTIONS:
                session.done = True
                await send_fn(ServerMessage(
                    session_id=session.session_id,
                    type="action",
                    action=AskUserAction(
                        question=(
                            "I am stuck repeating the same action because the screen is not changing. "
                            "Please perform the highlighted step manually, then rerun the agent."
                        ),
                        description="Repeated identical action detected on an unchanged screen.",
                    ),
                ))
                session.history.append({
                    "step": session.step,
                    "thinking": "Stopped to avoid a loop on an unchanged screen.",
                    "action": {
                        "type": "ask_user",
                        "question": "Manual intervention required.",
                    },
                    "success": False,
                    "error": "Repeated identical action detected.",
                })
                return

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
            # Try to execute the action in Playwright (if automatable)
            result = await self._playwright.perform_action(action)
            history_entry["success"] = result.get("success", True)
            if not result.get("success", True):
                history_entry["error"] = result.get("error")
            session.history.append(history_entry)

            # Report result to frontend
            await send_fn(ServerMessage(
                session_id=session.session_id,
                type="action",
                action=action,
            ))
            # Also set action result for session (for compatibility)
            session.last_action_success = result.get("success", True)
            session.last_action_error = result.get("error")
            session.action_result_ready.set()

        if not session.done:
            await send_fn(ServerMessage(
                session_id=session.session_id,
                type="status",
                status=(
                    f"⚠️ Reached maximum steps ({MAX_STEPS}). Session ended. "
                    f"Run again for the next step."
                ),
            ))

        # Close Playwright browser
        await self._playwright.close()

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

    @staticmethod
    def _action_signature(action_dict: dict) -> str:
        return json.dumps(action_dict, sort_keys=True, ensure_ascii=True)
