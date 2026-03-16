"""
Gemini API client — uses the google-genai SDK (google.genai).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re

import google.auth
from google.auth.exceptions import DefaultCredentialsError

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class GeminiRateLimitError(Exception):
    """Raised when Gemini returns a quota/rate-limit response."""

    def __init__(self, message: str, retry_after_seconds: float = 30.0) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")

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
        use_vertex = os.environ.get("USE_VERTEX", "false").strip().lower() in {
            "1", "true", "yes", "on"
        }

        self.provider = "gemini-api"

        project_id = os.environ.get("GCP_PROJECT_ID", "").strip()
        location = os.environ.get("VERTEX_LOCATION", "us-central1").strip()
        api_key = os.environ.get("GOOGLE_API_KEY", "").strip()

        if use_vertex:
            if not project_id or project_id == "your-gcp-project-id":
                raise ValueError(
                    "USE_VERTEX=true but GCP_PROJECT_ID is not set to a real project id "
                    "in backend/.env."
                )
            try:
                google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
                self.client = genai.Client(
                    vertexai=True,
                    project=project_id,
                    location=location,
                )
                self.provider = "vertex"
            except DefaultCredentialsError as exc:
                if api_key:
                    logger.warning(
                        "USE_VERTEX=true but ADC credentials are missing. "
                        "Falling back to Gemini API key mode for local run. "
                        "Run 'gcloud auth application-default login' to use Vertex."
                    )
                    self.client = genai.Client(api_key=api_key)
                    self.provider = "gemini-api-fallback"
                else:
                    raise ValueError(
                        "USE_VERTEX=true but ADC credentials are missing and GOOGLE_API_KEY is empty. "
                        "Run 'gcloud auth application-default login' or set GOOGLE_API_KEY."
                    ) from exc
        else:
            if not api_key:
                raise ValueError(
                    "GOOGLE_API_KEY is not set. Add it to backend/.env and restart."
                )
            self.client = genai.Client(api_key=api_key)
            self.provider = "gemini-api"
        primary_model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-001").strip()
        fallback_models_raw = os.environ.get(
            "GEMINI_MODEL_FALLBACKS",
            "gemini-2.0-flash-lite-001",
        )
        fallback_models = [m.strip() for m in fallback_models_raw.split(",") if m.strip()]

        # Hard guard: avoid free-tier alias/model variants that resolve to 2.5-flash-lite
        # and quickly hit strict request limits. In Vertex mode, 2.5 may be the
        # only available family in a project/region, so allow it there.
        allow_25_models = self.provider == "vertex"

        def is_blocked_model(name: str) -> bool:
            lowered = name.lower()
            return (
                lowered == "gemini-flash-lite-latest"
                or ((not allow_25_models) and "2.5" in lowered)
                or lowered.startswith("gemini-3")
            )

        if is_blocked_model(primary_model):
            logger.warning(
                "GEMINI_MODEL '%s' is blocked for this app config; forcing gemini-2.0-flash.",
                primary_model,
            )
            primary_model = "gemini-2.0-flash-001"

        fallback_models = [m for m in fallback_models if not is_blocked_model(m)]

        seen: set[str] = set()
        self.model_candidates: list[str] = []
        for model in [primary_model, *fallback_models]:
            if model and model not in seen:
                seen.add(model)
                self.model_candidates.append(model)

        if not self.model_candidates:
            self.model_candidates = ["gemini-2.0-flash-001"]

        self.model = self.model_candidates[0]

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

        # Build text portion of the prompt
        text_prompt = "".join(
            p for p in prompt_parts if isinstance(p, str)
        )

        # Decode base64 image → bytes
        image_data = base64.b64decode(image_b64)

        contents = [
            types.Part.from_text(text=text_prompt),
            types.Part.from_bytes(data=image_data, mime_type="image/jpeg"),
        ]

        raw_text = ""
        last_rate_limit_error: GeminiRateLimitError | None = None
        last_not_found_error: Exception | None = None

        for model_name in self.model_candidates:
            try:
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.1,
                        max_output_tokens=1024,
                        response_mime_type="application/json",
                    ),
                )
                raw_text = response.text.strip()
                parsed = json.loads(raw_text)
                thinking = parsed.get("thinking", "")
                action = parsed.get("action", {})
                if model_name != self.model:
                    logger.info("Gemini fallback succeeded with model: %s", model_name)
                self.model = model_name
                return thinking, action
            except json.JSONDecodeError as e:
                logger.error("JSON parse error from Gemini: %s\nRaw: %s", e, raw_text)
                return "Could not parse response, requesting new screenshot.", {"type": "screenshot"}
            except Exception as e:
                message = str(e)
                if "NOT_FOUND" in message or "is not found" in message:
                    last_not_found_error = e
                    logger.warning(
                        "Gemini model not found/unsupported for generateContent: %s. Trying next fallback.",
                        model_name,
                    )
                    continue
                if "RESOURCE_EXHAUSTED" in message or "429" in message:
                    retry_after = self._extract_retry_after_seconds(message)
                    last_rate_limit_error = GeminiRateLimitError(
                        message=f"Model '{model_name}' rate-limited: {message}",
                        retry_after_seconds=retry_after,
                    )
                    logger.warning(
                        "Gemini model rate-limited: %s. Trying next fallback if available.",
                        model_name,
                    )
                    continue
                logger.exception("Gemini API error on model %s: %s", model_name, e)
                raise

        if last_rate_limit_error is not None:
            raise last_rate_limit_error

        if last_not_found_error is not None:
            raise RuntimeError(
                "No configured Gemini models were available for generateContent. "
                f"Checked: {self.model_candidates}"
            ) from last_not_found_error

        raise RuntimeError("Gemini call failed: no configured models could be used.")

    async def describe_screen(self, image_b64: str) -> str:
        """Return a plain-language description of what's on screen (for logging/UI)."""
        image_data = base64.b64decode(image_b64)
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=[
                types.Part.from_text(text="Describe this browser screenshot concisely in 1-2 sentences."),
                types.Part.from_bytes(data=image_data, mime_type="image/jpeg"),
            ],
            config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=200),
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

    @staticmethod
    def _extract_retry_after_seconds(message: str) -> float:
        """
        Parse retry hints from Gemini 429 payloads.
        Supports patterns like:
          - "Please retry in 51.09s"
          - "'retryDelay': '51s'"
        """
        patterns = [
            r"retry in\s+([0-9]+(?:\.[0-9]+)?)s",
            r"retryDelay'?:\s*'([0-9]+)s'",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                try:
                    return max(1.0, float(match.group(1)))
                except ValueError:
                    continue
        return 30.0
