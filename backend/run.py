"""
Launcher for ScreenPilot backend.

Run with:  python run.py

Sets WindowsProactorEventLoopPolicy BEFORE uvicorn creates the event loop,
which is necessary for Playwright to spawn subprocesses on Windows.
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
