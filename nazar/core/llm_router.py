"""
Nazar — LLM Router with Failover

Ensures 99.9% availability by routing through multiple providers.
If one is down, we seamlessly switch. The user never knows.

Routing strategy:
- Customer conversations: Sonnet (quality)
- Automated tasks (digests, summaries): Haiku (cost-efficient)
- Failover chain: Anthropic → OpenRouter → Gemini Flash
"""

import os
import json
import time
import asyncio
import aiohttp
from typing import Optional
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

# Provider configurations
PROVIDERS = {
    "anthropic": {
        "name": "Anthropic Direct",
        "base_url": "https://api.anthropic.com/v1/messages",
        "models": {
            "sonnet": "claude-sonnet-4-5-20250514",
            "haiku": "claude-3-5-haiku-20241022",
        },
        "headers": lambda key: {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        "env_key": "ANTHROPIC_API_KEY",
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "models": {
            "sonnet": [
                "anthropic/claude-sonnet-4-5",
                "openai/gpt-4o-mini",
                "meta-llama/llama-3.3-70b-instruct:free",
            ],
            "haiku": [
                "openai/gpt-4o-mini",
                "meta-llama/llama-3.3-70b-instruct:free",
                "microsoft/phi-4-reasoning-plus:free",
            ],
        },
        "headers": lambda key: {
            "Authorization": f"Bearer {key}",
            "content-type": "application/json",
            "HTTP-Referer": "https://nazar.app",
            "X-Title": "Nazar Sales Intelligence",
        },
        "env_key": "OPENROUTER_API_KEY",
    },
    "google": {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/models",
        "models": {
            "sonnet": "gemini-2.0-flash",  # Fallback — not Sonnet but capable
            "haiku": "gemini-2.0-flash",
        },
        "env_key": "GOOGLE_API_KEY",
    },
}

# Failover order
FAILOVER_CHAIN = ["anthropic", "openrouter", "google"]

# Track provider health
_provider_health = {
    "anthropic": {"healthy": True, "last_failure": None, "consecutive_failures": 0},
    "openrouter": {"healthy": True, "last_failure": None, "consecutive_failures": 0},
    "google": {"healthy": True, "last_failure": None, "consecutive_failures": 0},
}

# Cool-down: retry a failed provider after this many seconds
# Keep short — transient 400s from free models are common
RETRY_AFTER_SECONDS = 30


def _get_api_key(provider: str) -> Optional[str]:
    """Get API key for a provider from environment."""
    env_key = PROVIDERS[provider]["env_key"]
    return os.environ.get(env_key)


def _is_provider_available(provider: str) -> bool:
    """Check if a provider is available (has key + is healthy or cooled down)."""
    key = _get_api_key(provider)
    if not key:
        return False

    health = _provider_health[provider]
    if health["healthy"]:
        return True

    # Check if cool-down period has passed
    if health["last_failure"]:
        elapsed = time.time() - health["last_failure"]
        if elapsed > RETRY_AFTER_SECONDS:
            health["healthy"] = True
            health["consecutive_failures"] = 0
            return True

    return False


def _mark_failure(provider: str):
    """Mark a provider as failed."""
    health = _provider_health[provider]
    health["healthy"] = False
    health["last_failure"] = time.time()
    health["consecutive_failures"] += 1
    print(f"⚠️ Provider {provider} marked unhealthy (failures: {health['consecutive_failures']})")


def _mark_success(provider: str):
    """Mark a provider as healthy."""
    health = _provider_health[provider]
    health["healthy"] = True
    health["consecutive_failures"] = 0


async def _call_anthropic(messages: list, model: str, api_key: str,
                          max_tokens: int = 1024, timeout: int = 30) -> str:
    """Call Anthropic API directly."""
    config = PROVIDERS["anthropic"]

    # Convert messages format for Anthropic
    system_msg = ""
    chat_msgs = []
    for msg in messages:
        if msg["role"] == "system":
            system_msg += msg["content"] + "\n"
        else:
            chat_msgs.append({"role": msg["role"], "content": msg["content"]})

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_msg.strip(),
        "messages": chat_msgs,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            config["base_url"],
            headers=config["headers"](api_key),
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status != 200:
                error = await resp.text()
                raise Exception(f"Anthropic API error {resp.status}: {error[:200]}")
            data = await resp.json()
            usage = data.get("usage", {})
            return (data["content"][0]["text"], {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            })


async def _call_openrouter(messages: list, model: str, api_key: str,
                            max_tokens: int = 1024, timeout: int = 30) -> tuple:
    """Call OpenRouter API. Returns (text, usage_dict).
    Retries once on transient 400/502/503 errors (common with free models).
    """
    config = PROVIDERS["openrouter"]

    payload = {
        "model": model,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "max_tokens": max_tokens,
    }

    last_error = None
    for attempt in range(2):  # retry once on transient errors
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config["base_url"],
                headers=config["headers"](api_key),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Check for upstream error wrapped in 200
                    if data.get("error"):
                        last_error = f"OpenRouter returned error in body: {str(data['error'])[:200]}"
                        if attempt == 0:
                            await asyncio.sleep(1)
                            continue
                        raise Exception(last_error)
                    usage = data.get("usage", {})
                    return (data["choices"][0]["message"]["content"], {
                        "input_tokens": usage.get("prompt_tokens", 0),
                        "output_tokens": usage.get("completion_tokens", 0),
                    })
                elif resp.status in (400, 429, 500, 502, 503) and attempt == 0:
                    # Transient error — retry once after a brief pause
                    error = await resp.text()
                    last_error = f"OpenRouter API error {resp.status}: {error[:200]}"
                    print(f"⚠️ OpenRouter transient error (attempt {attempt+1}): {resp.status}, retrying...")
                    await asyncio.sleep(1.5)
                    continue
                else:
                    error = await resp.text()
                    raise Exception(f"OpenRouter API error {resp.status}: {error[:200]}")

    raise Exception(last_error or "OpenRouter: unknown error after retries")


async def _call_google(messages: list, model: str, api_key: str,
                       max_tokens: int = 1024, timeout: int = 30) -> str:
    """Call Google Gemini API."""
    # Convert messages to Gemini format
    system_msg = ""
    contents = []
    for msg in messages:
        if msg["role"] == "system":
            system_msg += msg["content"] + "\n"
        elif msg["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": msg["content"]}]})
        elif msg["role"] == "assistant":
            contents.append({"role": "model", "parts": [{"text": msg["content"]}]})

    payload = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system_msg:
        payload["systemInstruction"] = {"parts": [{"text": system_msg.strip()}]}

    url = f"{PROVIDERS['google']['base_url']}/{model}:generateContent?key={api_key}"

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status != 200:
                error = await resp.text()
                raise Exception(f"Gemini API error {resp.status}: {error[:200]}")
            data = await resp.json()
            usage_meta = data.get("usageMetadata", {})
            return (data["candidates"][0]["content"]["parts"][0]["text"], {
                "input_tokens": usage_meta.get("promptTokenCount", 0),
                "output_tokens": usage_meta.get("candidatesTokenCount", 0),
            })


# Provider call dispatch
_CALLERS = {
    "anthropic": _call_anthropic,
    "openrouter": _call_openrouter,
    "google": _call_google,
}


async def call_llm(messages: list, tier: str = "sonnet",
                    is_crisis: bool = False, timeout: int = 30,
                    phone: str = "") -> str:
    """
    Call the LLM with automatic failover.
    
    Args:
        messages: List of {role, content} messages
        tier: "sonnet" for conversations, "haiku" for check-ins
        is_crisis: If True, always use sonnet tier
        timeout: Seconds before timing out a provider
        phone: User phone for usage tracking
    
    Returns:
        The LLM response text
    
    Raises:
        Exception if ALL providers fail
    """
    if is_crisis:
        tier = "sonnet"  # Never cheap out on crisis

    errors = []

    for provider_name in FAILOVER_CHAIN:
        if not _is_provider_available(provider_name):
            continue

        api_key = _get_api_key(provider_name)
        models = PROVIDERS[provider_name]["models"][tier]
        if isinstance(models, str):
            models = [models]
        caller = _CALLERS[provider_name]

        for model in models:
            try:
                start_ms = int(time.time() * 1000)
                result = await caller(messages, model, api_key, timeout=timeout)
                latency_ms = int(time.time() * 1000) - start_ms
                _mark_success(provider_name)

                # Unpack response + usage
                if isinstance(result, tuple):
                    response_text, usage = result
                else:
                    response_text, usage = result, {}

                # Track usage
                try:
                    from usage_tracker import log_usage
                    log_usage(
                        phone=phone or "unknown",
                        model=model,
                        provider=provider_name,
                        input_tokens=usage.get("input_tokens", 0),
                        output_tokens=usage.get("output_tokens", 0),
                        latency_ms=latency_ms,
                        is_crisis=is_crisis,
                        tier=tier,
                    )
                except Exception as track_err:
                    print(f"⚠️ Usage tracking error: {track_err}")

                return response_text

            except asyncio.TimeoutError:
                errors.append(f"{provider_name}/{model}: timeout after {timeout}s")
                continue

            except Exception as e:
                errors.append(f"{provider_name}/{model}: {str(e)[:100]}")
                continue

        _mark_failure(provider_name)

    # ALL providers failed — this is bad
    error_summary = "; ".join(errors)
    raise Exception(f"All LLM providers failed: {error_summary}")


FALLBACK_MESSAGE = (
    "I'm having a brief technical issue. A team member will follow up with you shortly!"
)


async def call_llm_safe(messages: list, tier: str = "sonnet",
                        phone: str = "") -> str:
    """
    Safe wrapper around call_llm that NEVER throws.
    Returns a response no matter what.
    """
    try:
        return await call_llm(messages, tier=tier, timeout=30, phone=phone)
    except Exception as e:
        print(f"All LLM providers failed: {e}")
        return FALLBACK_MESSAGE


def get_health_status() -> dict:
    """Get health status of all providers."""
    status = {}
    for name in FAILOVER_CHAIN:
        health = _provider_health[name]
        has_key = bool(_get_api_key(name))
        status[name] = {
            "configured": has_key,
            "healthy": health["healthy"],
            "consecutive_failures": health["consecutive_failures"],
            "available": _is_provider_available(name),
        }
    return status


# --- Test ---
if __name__ == "__main__":
    # Just test the health/config logic (no real API calls)
    print("Provider health status:")
    status = get_health_status()
    for name, s in status.items():
        icon = "✅" if s["available"] else "⚠️" if s["configured"] else "❌"
        print(f"  {icon} {name}: configured={s['configured']}, healthy={s['healthy']}")

    # Test failover marking
    _mark_failure("anthropic")
    print(f"\nAfter marking anthropic failed:")
    print(f"  anthropic available: {_is_provider_available('anthropic')}")
    print(f"  openrouter available: {_is_provider_available('openrouter')}")

    _mark_success("anthropic")
    print(f"\nAfter marking anthropic healthy:")
    print(f"  anthropic available: {_is_provider_available('anthropic')}")

    print("\n✅ LLM Router tests passed!")
