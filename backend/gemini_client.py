"""
Gemini API client — wraps google-generativeai for both standard multimodal
calls (vision analysis) and the Live API (streaming audio/video).
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Optional

import google.generativeai as genai
from google.generativeai.types import HarmBlockThreshold, HarmCategory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

genai.configure(api_key=GOOGLE_API_KEY)

# Safety settings — permissive for automation tasks
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ---------------------------------------------------------------------------
# System prompt (injected into every analysis call)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are ScreenPilot, an expert AI agent that controls a user's browser to accomplish tasks.

You receive:
1. A screenshot of the current browser state (base64-encoded image)
2. The user's high-level goal
3. The history of actions already taken

You must respond ONLY with a JSON object matching one of the action schemas below.
Before outputting the JSON, include a brief "thinking" field explaining your reasoning.

Available actions:
- click:          {"type":"click","x":0.5,"y":0.3,"description":"..."}
- right_click:    {"type":"right_click","x":0.5,"y":0.3,"description":"..."}
- double_click:   {"type":"double_click","x":0.5,"y":0.3,"description":"..."}
- hover:          {"type":"hover","x":0.5,"y":0.3,"description":"..."}
- type:           {"type":"type","text":"hello world","description":"..."}
- clear_and_type: {"type":"clear_and_type","x":0.4,"y":0.2,"text":"...","description":"..."}
- key_press:      {"type":"key_press","key":"Enter","modifiers":[],"description":"..."}
- scroll:         {"type":"scroll","x":0.5,"y":0.5,"delta_x":0,"delta_y":300,"description":"..."}
- navigate:       {"type":"navigate","url":"https://example.com","description":"..."}
- wait:           {"type":"wait","ms":1500,"description":"..."}
- screenshot:     {"type":"screenshot","description":"Request fresh screenshot"}
- done:           {"type":"done","summary":"Task completed: ..."}
- ask_user:       {"type":"ask_user","question":"...","description":"..."}

IMPORTANT rules:
- Coordinates (x, y) are NORMALISED [0.0 – 1.0], where (0,0) = top-left.
- Always prefer the most specific, targeted action.
- Never guess a URL — use navigation only when you know the exact URL or the
  user has provided it. Otherwise click links/buttons visible on screen.
- If the page is still loading, emit a wait action.
- When the goal is fully complete, emit done.
- If you are stuck after 3 failed attempts on the same step, emit ask_user.

Respond EXACTLY in this JSON structure:
{
  "thinking": "<your step-by-step reasoning>",
  "action": { <action object> }
}
"""


# ---------------------------------------------------------------------------
# GeminiClient
# ---------------------------------------------------------------------------

class GeminiClient:
    """Thin async-friendly wrapper around the Gemini generative model."""

    def __init__(self) -> None:
        self.model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT,
            safety_settings=SAFETY_SETTINGS,
        )

    async def analyze_screen(
        self,
        image_b64: str,
        goal: str,
        history: list[dict],
        screen_width: int = 1280,
        screen_height: int = 720,
    ) -> tuple[str, dict]:
        """
        Send screenshot + goal + history to Gemini and parse the response.

        Returns:
            (thinking_text, action_dict)
        """
        # Build history context string
        history_text = self._format_history(history)

        prompt_parts = [
            f"Goal: {goal}\n\n",
            f"Screen dimensions: {screen_width}x{screen_height}\n\n",
        ]

        if history_text:
            prompt_parts.append(f"Actions taken so far:\n{history_text}\n\n")

        prompt_parts.append("Current screenshot:")

        # Decode base64 image → inline data
        image_data = base64.b64decode(image_b64)
        image_part = {"mime_type": "image/jpeg", "data": image_data}

        try:
            response = await self.model.generate_content_async(
                [*prompt_parts, image_part],
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=1024,
                    response_mime_type="application/json",
                ),
            )
            raw_text = response.text.strip()
            parsed = json.loads(raw_text)
            thinking = parsed.get("thinking", "")
            action = parsed.get("action", {})
            return thinking, action
        except json.JSONDecodeError as e:
            logger.error("JSON parse error from Gemini: %s\nRaw: %s", e, raw_text)
            # Fallback: request a fresh screenshot
            return "Could not parse response, requesting new screenshot.", {"type": "screenshot"}
        except Exception as e:
            logger.exception("Gemini API error: %s", e)
            raise

    async def describe_screen(self, image_b64: str) -> str:
        """Return a plain-language description of what's on screen (for logging/UI)."""
        image_data = base64.b64decode(image_b64)
        image_part = {"mime_type": "image/jpeg", "data": image_data}
        response = await self.model.generate_content_async(
            ["Describe this browser screenshot concisely in 1-2 sentences.", image_part],
            generation_config=genai.types.GenerationConfig(temperature=0.2, max_output_tokens=200),
        )
        return response.text.strip()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_history(history: list[dict]) -> str:
        if not history:
            return ""
        lines = []
        for i, entry in enumerate(history[-10:], 1):  # last 10 steps only
            action_type = entry.get("action", {}).get("type", "unknown")
            thinking = entry.get("thinking", "")
            success = "✓" if entry.get("success", True) else "✗"
            lines.append(f"  {i}. [{success}] {action_type} — {thinking[:80]}")
        return "\n".join(lines)
