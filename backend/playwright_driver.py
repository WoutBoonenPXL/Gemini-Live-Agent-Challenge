# playwright_driver.py
"""
Playwright browser automation driver for ScreenPilotAgent.

Key design: Playwright runs on its own dedicated background thread with an
explicit ProactorEventLoop (required for subprocess creation on Windows).
This completely sidesteps uvicorn's SelectorEventLoop, which raises
NotImplementedError for create_subprocess_exec on Windows.

All public methods are async and safe to await from uvicorn's event loop.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from typing import Optional

from action_models import (
    AgentAction,
    AskUserAction,
    ClickAction,
    ClearAndTypeAction,
    DoubleClickAction,
    DoneAction,
    HoverAction,
    KeyPressAction,
    NavigateAction,
    RightClickAction,
    ScreenshotAction,
    ScrollAction,
    TypeAction,
    WaitAction,
)


# ---------------------------------------------------------------------------
# Dedicated background thread — owns a ProactorEventLoop for Playwright
# ---------------------------------------------------------------------------

class _PlaywrightThread:
    """
    Starts a background thread running a ProactorEventLoop (Windows) or a
    plain new event loop (other platforms).  Coroutines are submitted via
    run_async(), which bridges back to the caller's asyncio event loop.
    """

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="playwright-loop"
        )
        self._thread.start()
        if not self._ready.wait(timeout=15):
            raise RuntimeError("Playwright background thread failed to start.")

    def _run_loop(self) -> None:
        if sys.platform == "win32":
            loop: asyncio.AbstractEventLoop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()

    async def run_async(self, coro):
        """
        Schedule *coro* on the Playwright thread and await its result from
        any external event loop (e.g. uvicorn's SelectorEventLoop).
        """
        caller_loop = asyncio.get_event_loop()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return await caller_loop.run_in_executor(None, future.result)


# Singleton — one shared Playwright thread for the whole process
_pw_thread_lock = threading.Lock()
_pw_thread_instance: Optional[_PlaywrightThread] = None


def _get_pw_thread() -> _PlaywrightThread:
    global _pw_thread_instance
    if _pw_thread_instance is None:
        with _pw_thread_lock:
            if _pw_thread_instance is None:
                _pw_thread_instance = _PlaywrightThread()
    return _pw_thread_instance


# ---------------------------------------------------------------------------
# Public async driver
# ---------------------------------------------------------------------------

class PlaywrightDriver:
    """
    Async API for controlling a Playwright Chromium browser.
    Safe to use from any asyncio event loop, including uvicorn's SelectorEventLoop.
    """

    def __init__(self) -> None:
        self._browser = None
        self._page = None
        self._pw = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def launch(self, headless: bool = True) -> None:
        await _get_pw_thread().run_async(self._async_launch(headless))

    async def _async_launch(self, headless: bool) -> None:
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=headless)
        self._page = await self._browser.new_page()

    async def close(self) -> None:
        await _get_pw_thread().run_async(self._async_close())

    async def _async_close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    # ------------------------------------------------------------------
    # Navigation & screenshot
    # ------------------------------------------------------------------

    async def goto(self, url: str) -> None:
        await _get_pw_thread().run_async(self._page.goto(url))

    async def screenshot(self) -> bytes:
        return await _get_pw_thread().run_async(self._page.screenshot())

    @property
    def viewport_size(self) -> Optional[dict]:
        return self._page.viewport_size if self._page else None

    # ------------------------------------------------------------------
    # Action dispatcher
    # ------------------------------------------------------------------

    async def perform_action(self, action: AgentAction) -> dict:
        """Execute *action* in the browser. Returns {success, error?}."""
        try:
            await _get_pw_thread().run_async(self._dispatch(action))
            return {"success": True}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _dispatch(self, action: AgentAction) -> None:
        if isinstance(action, ClickAction):
            x, y = self._px(action.x, action.y)
            await self._page.mouse.click(x, y)
        elif isinstance(action, RightClickAction):
            x, y = self._px(action.x, action.y)
            await self._page.mouse.click(x, y, button="right")
        elif isinstance(action, DoubleClickAction):
            x, y = self._px(action.x, action.y)
            await self._page.mouse.dblclick(x, y)
        elif isinstance(action, HoverAction):
            x, y = self._px(action.x, action.y)
            await self._page.mouse.move(x, y)
        elif isinstance(action, TypeAction):
            await self._page.keyboard.type(action.text)
        elif isinstance(action, ClearAndTypeAction):
            x, y = self._px(action.x, action.y)
            await self._page.mouse.click(x, y)
            await self._page.keyboard.press("Control+A")
            await self._page.keyboard.press("Backspace")
            await self._page.keyboard.type(action.text)
        elif isinstance(action, KeyPressAction):
            chord = "+".join(
                [m.capitalize() for m in action.modifiers] + [action.key]
            )
            await self._page.keyboard.press(chord)
        elif isinstance(action, ScrollAction):
            await self._page.mouse.wheel(action.delta_x, action.delta_y)
        elif isinstance(action, NavigateAction):
            await self._page.goto(action.url)
        elif isinstance(action, WaitAction):
            await asyncio.sleep(action.ms / 1000)
        # ScreenshotAction / DoneAction / AskUserAction — no browser op needed

    def _px(self, norm_x: float, norm_y: float) -> tuple[int, int]:
        """Convert normalised [0, 1] coordinates to viewport pixels."""
        vp = self._page.viewport_size or {"width": 1280, "height": 720}
        return int(norm_x * vp["width"]), int(norm_y * vp["height"])
