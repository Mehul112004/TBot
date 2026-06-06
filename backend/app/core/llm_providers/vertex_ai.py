import logging
import time
from typing import Tuple, Optional

from google import genai
from google.genai import types

from app.core.llm_providers.base import BaseLLMProvider

logger = logging.getLogger(__name__)

RETRYABLE_MESSAGES = {"rate limit", "timeout", "connection", "unavailable", "internal server error", "resource exhausted"}


class VertexAIProvider(BaseLLMProvider):
    """
    Provider for Vertex AI (Gemini and partner models) using Application Default Credentials.
    Uses the native google-genai SDK with enterprise=True for ADC authentication.
    """

    MAX_RETRIES = 3
    RETRY_DELAYS = [5, 20, 60]

    def __init__(
        self,
        project_id: str,
        location: str,
        model: str = "gemini-3.5-flash",
        max_tokens: int = 65535,
        temperature: float = 0.2,
        thinking_level: Optional[str] = None,
    ):
        self.project_id = project_id
        self.location = location
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.thinking_level = thinking_level

        logger.info(
            f"[VertexAIProvider] Initializing client for project={project_id}, "
            f"location={location}, model={model}"
        )

        self.client = genai.Client(
            enterprise=True,
            project=project_id,
            location=location,
        )

    def evaluate_prompt(self, system_prompt: str, user_prompt: str) -> Tuple[Optional[str], str]:
        config_kwargs = {
            "system_instruction": system_prompt,
            "temperature": self.temperature,
            "max_output_tokens": self.max_tokens,
            "response_mime_type": "application/json"
        }

        if self.thinking_level:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=self.thinking_level,
            )

        config = types.GenerateContentConfig(**config_kwargs)

        last_error = ""
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                logger.info(
                    f"[VertexAIProvider] Sending request (model={self.model})"
                    f"{f', attempt {attempt + 1}/{self.MAX_RETRIES + 1}' if attempt > 0 else ''}"
                )

                response = self.client.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=config,
                )

                content = response.text
                if content is None:
                    content = ""

                content = content.strip()

                if not content:
                    finish_reason = None
                    if response.candidates:
                        candidate = response.candidates[0]
                        finish_reason = getattr(candidate, 'finish_reason', None)
                    logger.error(
                        f"[VertexAIProvider] Empty response content. "
                        f"Finish reason: {finish_reason}"
                    )
                    if finish_reason and "MAX_TOKENS" in str(finish_reason).upper():
                        return None, "ERROR: Truncated text/Exceeded max tokens. Prompt might be too long."
                    return None, response.model_dump_json()

                return content, response.model_dump_json()

            except Exception as e:
                error_str = str(e).lower()
                logger.error(f"[VertexAIProvider] Error: {e}")

                is_retryable = any(msg in error_str for msg in RETRYABLE_MESSAGES)

                if not is_retryable:
                    return None, f"ERROR: {e}"

                last_error = f"ERROR: {e}"

                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)]
                    logger.info(f"[VertexAIProvider] Retrying in {delay}s...")
                    for _ in range(delay):
                        time.sleep(1)

        return None, last_error

    def ping_status(self) -> bool:
        return True
