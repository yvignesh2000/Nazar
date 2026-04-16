"""Tests for service_window module."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from datetime import datetime, timezone, timedelta
from service_window import compute_window, batch_window_status, classify_campaign_targets

IST = timezone(timedelta(hours=5, minutes=30))


def _now():
    return datetime.now(IST)


def test_window_open_recent_inbound():
    """Window should be open for contact who messaged 1 hour ago."""
    now = _now()
    one_hour_ago = (now - timedelta(hours=1)).isoformat()
    contact = {"last_replied_at": one_hour_ago}
    result = compute_window(contact, now)
    assert result["window_open"] is True
    assert result["can_send_freeform"] is True
    assert result["requires_template"] is False
    assert result["hours_remaining"] > 22  # ~23 hours remaining


def test_window_closed_old_inbound():
    """Window should be closed for contact who messaged 25 hours ago."""
    now = _now()
    old = (now - timedelta(hours=25)).isoformat()
    contact = {"last_replied_at": old}
    result = compute_window(contact, now)
    assert result["window_open"] is False
    assert result["can_send_freeform"] is False
    assert result["requires_template"] is True
    assert result["hours_remaining"] == 0
    assert result["warning"] is not None
    assert "closed" in result["warning"].lower()


def test_window_no_inbound():
    """Window should be closed if contact never messaged us."""
    contact = {"last_replied_at": None}
    result = compute_window(contact)
    assert result["window_open"] is False
    assert result["requires_template"] is True
    assert result["warning"] is not None


def test_window_empty_string_inbound():
    """Window should be closed if last_replied_at is empty string."""
    contact = {"last_replied_at": ""}
    result = compute_window(contact)
    assert result["window_open"] is False
    assert result["requires_template"] is True


def test_window_closing_soon_warning():
    """Should have warning when window closing within 2 hours."""
    now = _now()
    almost_expired = (now - timedelta(hours=22, minutes=30)).isoformat()
    contact = {"last_replied_at": almost_expired}
    result = compute_window(contact, now)
    assert result["window_open"] is True
    assert result["hours_remaining"] < 2
    assert result["warning"] is not None
    assert "closing soon" in result["warning"].lower()


def test_window_no_warning_when_plenty_of_time():
    """Should have no warning when plenty of time left."""
    now = _now()
    recent = (now - timedelta(hours=5)).isoformat()
    contact = {"last_replied_at": recent}
    result = compute_window(contact, now)
    assert result["window_open"] is True
    assert result["warning"] is None


def test_batch_window_status():
    """batch_window_status should return dict keyed by contact_id."""
    now = _now()
    contacts = [
        {"contact_id": "c1", "last_replied_at": (now - timedelta(hours=1)).isoformat()},
        {"contact_id": "c2", "last_replied_at": (now - timedelta(hours=25)).isoformat()},
        {"contact_id": "c3", "last_replied_at": None},
    ]
    results = batch_window_status(contacts, now)
    assert len(results) == 3
    assert results["c1"]["window_open"] is True
    assert results["c2"]["window_open"] is False
    assert results["c3"]["window_open"] is False


def test_classify_campaign_targets():
    """classify_campaign_targets should split contacts into open/closed."""
    now = _now()
    contacts = [
        {"contact_id": "c1", "last_replied_at": (now - timedelta(hours=1)).isoformat()},
        {"contact_id": "c2", "last_replied_at": (now - timedelta(hours=25)).isoformat()},
        {"contact_id": "c3", "last_replied_at": None},
    ]
    result = classify_campaign_targets(contacts, now)
    assert result["summary"]["open_count"] == 1
    assert result["summary"]["closed_count"] == 2
    assert result["summary"]["total"] == 3
    assert len(result["window_open"]) == 1
    assert len(result["window_closed"]) == 2


def test_window_exact_24h_boundary():
    """At exactly 24h, window should be closed."""
    now = _now()
    exactly_24h = (now - timedelta(hours=24)).isoformat()
    contact = {"last_replied_at": exactly_24h}
    result = compute_window(contact, now)
    assert result["window_open"] is False


def test_window_just_under_24h():
    """At 23h 59m, window should still be open."""
    now = _now()
    almost_24h = (now - timedelta(hours=23, minutes=59)).isoformat()
    contact = {"last_replied_at": almost_24h}
    result = compute_window(contact, now)
    assert result["window_open"] is True


def test_window_returns_expires_at():
    """Window should return expires_at when open."""
    now = _now()
    recent = (now - timedelta(hours=5)).isoformat()
    contact = {"last_replied_at": recent}
    result = compute_window(contact, now)
    assert result["expires_at"] is not None
    # Should be parseable as ISO datetime
    datetime.fromisoformat(result["expires_at"])


def test_window_no_expires_at_when_closed():
    """Window should return None expires_at when closed."""
    now = _now()
    old = (now - timedelta(hours=30)).isoformat()
    contact = {"last_replied_at": old}
    result = compute_window(contact, now)
    assert result["expires_at"] is None
