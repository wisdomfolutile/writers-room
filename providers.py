"""
Provider registry for Writers Room BYOK multi-provider support.

Uses the OpenAI SDK's base_url pattern — zero new dependencies.
Every provider speaks the OpenAI-compatible chat completions API.
"""

from __future__ import annotations

PROVIDERS = {
    "openai": {
        "display_name": "OpenAI",
        "base_url": None,
        "synthesis_model": "gpt-4o-mini",
        "key_url": "https://platform.openai.com/api-keys",
        "key_prefix": "sk-",
    },
    "groq": {
        "display_name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "synthesis_model": "llama-3.1-8b-instant",
        "key_url": "https://console.groq.com/keys",
        "key_prefix": "gsk_",
    },
    "mistral": {
        "display_name": "Mistral",
        "base_url": "https://api.mistral.ai/v1",
        "synthesis_model": "mistral-small-latest",
        "key_url": "https://console.mistral.ai/api-keys",
        "key_prefix": "",
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "synthesis_model": "deepseek-chat",
        "key_url": "https://platform.deepseek.com/api_keys",
        "key_prefix": "sk-",
    },
    "openrouter": {
        "display_name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "synthesis_model": "openai/gpt-4o-mini",
        "key_url": "https://openrouter.ai/keys",
        "key_prefix": "sk-or-",
    },
}


def get_synthesis_client(provider_id: str, api_key: str):
    """Return (OpenAI_client, model_name) for the given provider."""
    from openai import OpenAI

    provider = PROVIDERS[provider_id]
    kwargs = {"api_key": api_key}
    if provider["base_url"]:
        kwargs["base_url"] = provider["base_url"]
    return OpenAI(**kwargs), provider["synthesis_model"]


def test_connection(provider_id: str, api_key: str) -> dict:
    """Validate an API key with a minimal 1-token completion. Returns {"ok": True} or {"ok": False, "error": "..."}."""
    try:
        client, model = get_synthesis_client(provider_id, api_key)
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=1,
        )
        return {"ok": True}
    except Exception as e:
        msg = str(e)
        # Extract user-friendly message from common error shapes
        if "401" in msg or "Unauthorized" in msg or "invalid" in msg.lower():
            return {"ok": False, "error": "Invalid API key. Check that you copied it correctly."}
        if "429" in msg or "rate" in msg.lower():
            return {"ok": False, "error": "Rate limit reached. Try again in a moment."}
        if "Connection" in msg or "resolve" in msg.lower():
            return {"ok": False, "error": "Could not reach the provider. Check your internet connection."}
        return {"ok": False, "error": msg}
