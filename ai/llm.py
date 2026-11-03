import logging
import httpx
from django.conf import settings
from ai.constants import MAX_TOKENS, TIME_OUT_SECONDS

logger = logging.getLogger(__name__)
URL = "https://api.anthropic.com/v1/messages"

class LLMError(Exception):
    pass

def generate(system, user_message):
    try:
        response = httpx.post(
            URL,
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",    
            },
            json={
                "model": settings.ANTHROPIC_MODEL,
                "max_tokens": MAX_TOKENS,
                "system": system,
                "messages": [
                    {"role": "user", "content": user_message}
                ]
            },
            timeout=TIME_OUT_SECONDS
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.exception("LLM request failed")
        raise LLMError("LLM request failed") from exc
    
    data = response.json()
    blocks = data.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    if not text:
        logger.error(
            "LLM returned no text block: types=%s stop_reason=%s",
            [b.get("type") for b in blocks],
            data.get("stop_reason"),
    )
        raise LLMError("LLM response missing text")
    return text