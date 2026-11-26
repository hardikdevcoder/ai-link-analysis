"""One function, call_llm(), that works with Gemini, Anthropic or OpenAI.

The rest of the app does not care which provider is used. Provider and model
come from .env (LLM_PROVIDER, LLM_MODEL) unless benchmark.py overrides them.
"""
import asyncio
from typing import Optional, Tuple

from app.config import settings

MAX_OUTPUT_TOKENS = 8192
RETRYABLE_CODES = (429, 500, 502, 503, 504)


def _api_key(provider: str) -> str:
    """Provider-specific key first, then the general LLM_API_KEY for the default provider."""
    specific = {
        "gemini": settings.gemini_api_key,
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
    }.get(provider, "")
    if specific:
        return specific
    if provider == settings.llm_provider:
        return settings.llm_api_key
    return ""


def has_key(provider: str) -> bool:
    return bool(_api_key(provider))


def _is_retryable(error: Exception) -> bool:
    """429 (rate limit) and 5xx (provider overloaded) are worth retrying."""
    code = getattr(error, "status_code", None) or getattr(error, "code", None)
    return code in RETRYABLE_CODES


# ---------------- Gemini ----------------
async def _call_gemini(system_prompt: str, user_prompt: str, model: str) -> Tuple[str, dict]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_api_key("gemini"))
    resp = await client.aio.models.generate_content(
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
        ),
    )
    meta = resp.usage_metadata
    usage = {
        "input_tokens": getattr(meta, "prompt_token_count", 0) or 0,
        "output_tokens": getattr(meta, "candidates_token_count", 0) or 0,
        "thinking_tokens": getattr(meta, "thoughts_token_count", 0) or 0,
    }
    return resp.text or "", usage


# ---------------- Anthropic (Claude) ----------------
async def _call_anthropic(system_prompt: str, user_prompt: str, model: str) -> Tuple[str, dict]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=_api_key("anthropic"))
    msg = await client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
    # Anthropic counts any thinking inside output_tokens, so thinking is reported as 0 here.
    usage = {
        "input_tokens": msg.usage.input_tokens,
        "output_tokens": msg.usage.output_tokens,
        "thinking_tokens": 0,
    }
    return text, usage


# ---------------- OpenAI ----------------
async def _call_openai(system_prompt: str, user_prompt: str, model: str) -> Tuple[str, dict]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=_api_key("openai"))
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=MAX_OUTPUT_TOKENS,
    )
    details = getattr(resp.usage, "completion_tokens_details", None)
    reasoning = (getattr(details, "reasoning_tokens", 0) or 0) if details else 0
    usage = {
        "input_tokens": resp.usage.prompt_tokens,
        # completion_tokens already includes reasoning tokens, so split them to avoid double counting
        "output_tokens": resp.usage.completion_tokens - reasoning,
        "thinking_tokens": reasoning,
    }
    return resp.choices[0].message.content or "", usage


_PROVIDERS = {
    "gemini": _call_gemini,
    "anthropic": _call_anthropic,
    "openai": _call_openai,
}


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Tuple[str, dict]:
    """Return (text, usage). usage = input_tokens, output_tokens, thinking_tokens.

    Retries up to 3 times on rate limits (429) and server errors (5xx),
    waiting longer each time. Other errors (bad key, bad model name) fail at once.
    """
    provider = (provider or settings.llm_provider).lower()
    model = model or settings.llm_model
    if provider not in _PROVIDERS:
        raise ValueError("Unknown LLM_PROVIDER '%s'. Use gemini, anthropic or openai." % provider)
    if not model:
        raise ValueError("LLM_MODEL is not set in .env")

    last_error = None
    for attempt in range(3):
        try:
            return await _PROVIDERS[provider](system_prompt, user_prompt, model)
        except Exception as e:                       # noqa: BLE001
            if not _is_retryable(e):
                raise
            last_error = e
            await asyncio.sleep(2 ** attempt * 5)    # wait 5s, 10s, 20s
    raise last_error