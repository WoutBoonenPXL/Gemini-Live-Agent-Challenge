"""
ScreenPilot Backend — FastAPI application.

Endpoints:
  GET  /           — health check
  GET  /health     — structured health check
  POST /session    — create a new agent session, returns session_id
  WS   /ws/{session_id}  — bidirectional WebSocket for screenshot frames
                           and action dispatch
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from action_models import ClientMessage, ServerMessage
from agent import AgentSession, ScreenPilotAgent

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

# In-memory session store (replace with Redis for multi-instance deployments)
SESSIONS: dict[str, AgentSession] = {}
AGENT = ScreenPilotAgent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ScreenPilot backend starting up…")
    yield
    logger.info("ScreenPilot backend shutting down.")
    SESSIONS.clear()


app = FastAPI(
    title="ScreenPilot API",
    description="AI UI Navigator Agent — Gemini Live Agent Challenge",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow frontend origin(s)
# ---------------------------------------------------------------------------

FRONTEND_ORIGINS = os.environ.get(
    "FRONTEND_ORIGINS",
    "http://localhost:3000,https://localhost:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.get("/")
async def root():
    return {"status": "ok", "service": "screenpilot-backend"}


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "model": os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
        "active_sessions": len(SESSIONS),
    }


class CreateSessionRequest(BaseModel):
    goal: str


class CreateSessionResponse(BaseModel):
    session_id: str


@app.post("/session", response_model=CreateSessionResponse)
async def create_session(body: CreateSessionRequest) -> CreateSessionResponse:
    """Create a new agent session for the given goal."""
    session = AgentSession(
        session_id=str(uuid.uuid4()),
        goal=body.goal,
    )
    SESSIONS[session.session_id] = session
    logger.info("Created session %s for goal: %s", session.session_id, body.goal)
    return CreateSessionResponse(session_id=session.session_id)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    logger.info("WebSocket connected: session=%s", session_id)

    # Retrieve or create session
    session = SESSIONS.get(session_id)
    if session is None:
        await websocket.send_json({"type": "error", "error": "Unknown session_id"})
        await websocket.close()
        return

    # Helper to push a ServerMessage to the client
    async def send_fn(msg: ServerMessage) -> None:
        try:
            await websocket.send_text(msg.model_dump_json())
        except Exception as exc:
            logger.warning("send_fn error: %s", exc)

    # Launch agent loop as a background task
    agent_task = asyncio.create_task(
        _run_agent(session, send_fn),
        name=f"agent-{session_id}",
    )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = ClientMessage.model_validate_json(raw)
            except Exception as exc:
                logger.warning("Malformed client message: %s", exc)
                continue

            await _handle_client_message(session, msg)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session=%s", session_id)
    except Exception as exc:
        logger.exception("WebSocket error: %s", exc)
    finally:
        agent_task.cancel()
        SESSIONS.pop(session_id, None)


async def _run_agent(session: AgentSession, send_fn) -> None:
    """Run the agent loop; handle graceful completion/errors."""
    try:
        async for _ in AGENT.run_session(session, send_fn):
            pass  # events are consumed internally
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.exception("Agent loop error for session %s: %s", session.session_id, exc)
        try:
            await send_fn(ServerMessage(
                session_id=session.session_id,
                type="error",
                error=f"Agent error: {exc}",
            ))
        except Exception:
            pass


async def _handle_client_message(session: AgentSession, msg: ClientMessage) -> None:
    """Route incoming client messages to the right session signal."""
    if msg.type == "screenshot":
        session.last_screenshot_b64 = msg.image_b64
        if msg.screen_width:
            session.screen_width = msg.screen_width
        if msg.screen_height:
            session.screen_height = msg.screen_height
        session.screenshot_ready.set()

    elif msg.type == "action_result":
        session.last_action_success = msg.action_success if msg.action_success is not None else True
        session.last_action_error = msg.action_error
        session.action_result_ready.set()

    elif msg.type == "command":
        # User updated the goal mid-session
        if msg.goal:
            logger.info("[%s] Goal updated to: %s", session.session_id, msg.goal)
            session.goal = msg.goal

    elif msg.type == "voice_chunk":
        # Audio chunks for Live API (future extension)
        pass
