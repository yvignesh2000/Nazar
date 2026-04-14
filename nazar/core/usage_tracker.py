"""
Nazar — LLM Usage Tracker

Tracks token usage, latency, and cost per provider/model.
Stores daily usage logs as JSONL for analytics and cost control.

Storage: data/usage/YYYY-MM-DD.jsonl
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data" / "usage"

# Approximate cost per 1M tokens (USD) — updated June 2025
MODEL_COSTS = {
    # Anthropic
    "claude-sonnet-4-5-20250514": {"input": 3.0, "output": 15.0},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.0},
    # OpenRouter (Claude via OR has same model cost + small markup)
    "anthropic/claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    # Free models on OpenRouter
    "google/gemma-3-27b-it:free": {"input": 0.0, "output": 0.0},
    # Google direct
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
}


def _usage_path(date_str: str) -> Path:
    """Get the usage log file path for a given date."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / f"{date_str}.jsonl"


def log_usage(
    phone: str,
    model: str,
    provider: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    is_crisis: bool = False,
    tier: str = "sonnet",
):
    """
    Log a single LLM call's usage.

    Args:
        phone: Customer phone number (for per-customer tracking).
        model: Model identifier used.
        provider: Provider name (anthropic, openrouter, google).
        input_tokens: Number of input/prompt tokens.
        output_tokens: Number of output/completion tokens.
        latency_ms: Response time in milliseconds.
        is_crisis: Whether this was a crisis-tier call.
        tier: LLM tier used (sonnet, haiku).
    """
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")

    # Estimate cost
    costs = MODEL_COSTS.get(model, {"input": 0.0, "output": 0.0})
    cost_usd = (
        (input_tokens / 1_000_000) * costs["input"]
        + (output_tokens / 1_000_000) * costs["output"]
    )

    entry = {
        "timestamp": now.isoformat(),
        "phone": phone[-4:] if len(phone) >= 4 else "****",  # Only last 4 digits for privacy
        "model": model,
        "provider": provider,
        "tier": tier,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "latency_ms": latency_ms,
        "cost_usd": round(cost_usd, 6),
        "is_crisis": is_crisis,
    }

    try:
        path = _usage_path(today)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Failed to log usage: {e}")


def get_daily_usage(date_str: Optional[str] = None) -> dict:
    """
    Get usage summary for a given date.

    Args:
        date_str: Date in YYYY-MM-DD format. Defaults to today.

    Returns:
        Dict with total_calls, total_tokens, total_cost, by_provider, by_tier.
    """
    if not date_str:
        date_str = datetime.now(IST).strftime("%Y-%m-%d")

    path = _usage_path(date_str)
    if not path.exists():
        return {
            "date": date_str,
            "total_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "avg_latency_ms": 0,
            "by_provider": {},
            "by_tier": {},
        }

    entries = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception as e:
        logger.warning(f"Failed to read usage for {date_str}: {e}")
        return {"date": date_str, "total_calls": 0, "error": str(e)}

    total_input = sum(e.get("input_tokens", 0) for e in entries)
    total_output = sum(e.get("output_tokens", 0) for e in entries)
    total_cost = sum(e.get("cost_usd", 0) for e in entries)
    latencies = [e.get("latency_ms", 0) for e in entries if e.get("latency_ms", 0) > 0]

    by_provider = {}
    by_tier = {}
    for e in entries:
        provider = e.get("provider", "unknown")
        tier = e.get("tier", "unknown")

        if provider not in by_provider:
            by_provider[provider] = {"calls": 0, "tokens": 0, "cost_usd": 0.0}
        by_provider[provider]["calls"] += 1
        by_provider[provider]["tokens"] += e.get("total_tokens", 0)
        by_provider[provider]["cost_usd"] += e.get("cost_usd", 0)

        if tier not in by_tier:
            by_tier[tier] = {"calls": 0, "tokens": 0, "cost_usd": 0.0}
        by_tier[tier]["calls"] += 1
        by_tier[tier]["tokens"] += e.get("total_tokens", 0)
        by_tier[tier]["cost_usd"] += e.get("cost_usd", 0)

    return {
        "date": date_str,
        "total_calls": len(entries),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "total_cost_usd": round(total_cost, 4),
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
        "by_provider": by_provider,
        "by_tier": by_tier,
    }


def get_monthly_summary() -> dict:
    """
    Get usage summary for the current month.

    Returns aggregate stats across all days in the current month.
    """
    now = datetime.now(IST)
    month_prefix = now.strftime("%Y-%m")

    if not DATA_DIR.exists():
        return {"month": month_prefix, "total_calls": 0, "total_cost_usd": 0.0, "days": []}

    total_calls = 0
    total_tokens = 0
    total_cost = 0.0
    days = []

    for path in sorted(DATA_DIR.glob(f"{month_prefix}-*.jsonl")):
        date_str = path.stem
        daily = get_daily_usage(date_str)
        total_calls += daily.get("total_calls", 0)
        total_tokens += daily.get("total_tokens", 0)
        total_cost += daily.get("total_cost_usd", 0)
        days.append({
            "date": date_str,
            "calls": daily.get("total_calls", 0),
            "tokens": daily.get("total_tokens", 0),
            "cost_usd": daily.get("total_cost_usd", 0),
        })

    return {
        "month": month_prefix,
        "total_calls": total_calls,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 4),
        "days": days,
    }


# --- Test ---
if __name__ == "__main__":
    import shutil

    # Clean
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)

    # Log some usage
    log_usage("+919876543210", "claude-sonnet-4-5-20250514", "anthropic",
              input_tokens=1500, output_tokens=300, latency_ms=1200, tier="sonnet")
    log_usage("+919876543211", "google/gemma-3-27b-it:free", "openrouter",
              input_tokens=800, output_tokens=200, latency_ms=600, tier="haiku")
    log_usage("+919876543210", "gemini-2.0-flash", "google",
              input_tokens=1000, output_tokens=250, latency_ms=900, tier="sonnet")

    # Read back
    daily = get_daily_usage()
    print(f"Daily usage: {json.dumps(daily, indent=2)}")
    assert daily["total_calls"] == 3
    assert daily["total_tokens"] > 0

    monthly = get_monthly_summary()
    print(f"\nMonthly summary: {json.dumps(monthly, indent=2)}")
    assert monthly["total_calls"] == 3

    # Cleanup
    shutil.rmtree(DATA_DIR)
    print("\n✅ Usage tracker tests passed!")
