"""
Pydantic models for every action the agent can dispatch to the frontend.
The frontend receives these as JSON over the WebSocket and renders overlays
/ dispatches synthetic DOM events accordingly.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Action type enum
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    CLICK = "click"
    RIGHT_CLICK = "right_click"
    DOUBLE_CLICK = "double_click"
    TYPE = "type"
    CLEAR_AND_TYPE = "clear_and_type"
    KEY_PRESS = "key_press"
    SCROLL = "scroll"
    NAVIGATE = "navigate"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    DONE = "done"
    ASK_USER = "ask_user"
    HOVER = "hover"


# ---------------------------------------------------------------------------
# Individual action payloads
# ---------------------------------------------------------------------------

class ClickAction(BaseModel):
    type: Literal[ActionType.CLICK] = ActionType.CLICK
    x: float = Field(..., description="Normalised X coordinate [0, 1]")
    y: float = Field(..., description="Normalised Y coordinate [0, 1]")
    description: str = ""


class RightClickAction(BaseModel):
    type: Literal[ActionType.RIGHT_CLICK] = ActionType.RIGHT_CLICK
    x: float
    y: float
    description: str = ""


class DoubleClickAction(BaseModel):
    type: Literal[ActionType.DOUBLE_CLICK] = ActionType.DOUBLE_CLICK
    x: float
    y: float
    description: str = ""


class HoverAction(BaseModel):
    type: Literal[ActionType.HOVER] = ActionType.HOVER
    x: float
    y: float
    description: str = ""


class TypeAction(BaseModel):
    type: Literal[ActionType.TYPE] = ActionType.TYPE
    text: str
    description: str = ""


class ClearAndTypeAction(BaseModel):
    type: Literal[ActionType.CLEAR_AND_TYPE] = ActionType.CLEAR_AND_TYPE
    x: float
    y: float
    text: str
    description: str = ""


class KeyPressAction(BaseModel):
    type: Literal[ActionType.KEY_PRESS] = ActionType.KEY_PRESS
    key: str = Field(..., description="Key name, e.g. 'Enter', 'Tab', 'ArrowDown'")
    modifiers: list[str] = Field(default_factory=list, description="e.g. ['ctrl', 'shift']")
    description: str = ""


class ScrollAction(BaseModel):
    type: Literal[ActionType.SCROLL] = ActionType.SCROLL
    x: float
    y: float
    delta_x: float = 0.0
    delta_y: float = Field(..., description="Pixels to scroll; positive = down")
    description: str = ""


class NavigateAction(BaseModel):
    type: Literal[ActionType.NAVIGATE] = ActionType.NAVIGATE
    url: str
    description: str = ""


class WaitAction(BaseModel):
    type: Literal[ActionType.WAIT] = ActionType.WAIT
    ms: int = Field(1000, description="Milliseconds to wait before next action")
    description: str = ""


class ScreenshotAction(BaseModel):
    type: Literal[ActionType.SCREENSHOT] = ActionType.SCREENSHOT
    description: str = "Request a fresh screenshot from the client"


class DoneAction(BaseModel):
    type: Literal[ActionType.DONE] = ActionType.DONE
    summary: str = Field(..., description="What was accomplished")


class AskUserAction(BaseModel):
    type: Literal[ActionType.ASK_USER] = ActionType.ASK_USER
    question: str
    description: str = ""


# ---------------------------------------------------------------------------
# Union type used across the codebase
# ---------------------------------------------------------------------------

AgentAction = Union[
    ClickAction,
    RightClickAction,
    DoubleClickAction,
    HoverAction,
    TypeAction,
    ClearAndTypeAction,
    KeyPressAction,
    ScrollAction,
    NavigateAction,
    WaitAction,
    ScreenshotAction,
    DoneAction,
    AskUserAction,
]


# ---------------------------------------------------------------------------
# WebSocket message envelopes
# ---------------------------------------------------------------------------

class ClientMessage(BaseModel):
    """Message sent FROM the browser TO the backend."""
    session_id: str
    type: Literal["command", "screenshot", "voice_chunk", "action_result"]
    # command
    goal: Optional[str] = None
    # screenshot
    image_b64: Optional[str] = None          # base64-encoded JPEG/PNG
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    # voice
    audio_b64: Optional[str] = None
    # action result
    action_success: Optional[bool] = None
    action_error: Optional[str] = None


class ServerMessage(BaseModel):
    """Message sent FROM the backend TO the browser."""
    session_id: str
    type: Literal["action", "thinking", "error", "status", "screenshot"]
    action: Optional[AgentAction] = None
    thinking: Optional[str] = None           # chain-of-thought narration
    error: Optional[str] = None
    status: Optional[str] = None
    image_b64: Optional[str] = None          # Playwright screenshot forwarded to frontend
