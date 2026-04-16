"""Tests for meta_template_sync module."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from meta_template_sync import _build_meta_template_payload, is_meta_configured


def test_build_payload_basic():
    template = {
        "name": "test_template",
        "language": "en",
        "category": "utility",
        "header": {"type": "none"},
        "body": "Hi {{1}}, welcome!",
        "footer": "Reply STOP to opt out",
        "buttons": [{"type": "quick_reply", "text": "Yes"}],
        "variables": ["name"],
    }
    payload = _build_meta_template_payload(template)
    assert payload["name"] == "test_template"
    assert payload["language"] == "en"
    assert payload["category"] == "UTILITY"
    types = [c["type"] for c in payload["components"]]
    assert "BODY" in types
    assert "FOOTER" in types
    assert "BUTTONS" in types


def test_build_payload_with_image_header():
    template = {
        "name": "image_template",
        "language": "en",
        "category": "marketing",
        "header": {"type": "image", "image_url": "https://example.com/img.jpg"},
        "body": "Check this out!",
        "footer": "",
        "buttons": [],
        "variables": [],
    }
    payload = _build_meta_template_payload(template)
    assert payload["category"] == "MARKETING"
    header_comp = [c for c in payload["components"] if c["type"] == "HEADER"]
    assert len(header_comp) == 1
    assert header_comp[0]["format"] == "IMAGE"


def test_build_payload_no_header():
    template = {
        "name": "no_header",
        "language": "en",
        "category": "utility",
        "header": {"type": "none"},
        "body": "Just body.",
        "footer": "",
        "buttons": [],
        "variables": [],
    }
    payload = _build_meta_template_payload(template)
    types = [c["type"] for c in payload["components"]]
    assert "HEADER" not in types


def test_build_payload_url_button():
    template = {
        "name": "url_btn",
        "language": "en",
        "category": "utility",
        "header": {"type": "none"},
        "body": "Visit us!",
        "footer": "",
        "buttons": [{"type": "url", "text": "Visit", "url": "https://example.com"}],
        "variables": [],
    }
    payload = _build_meta_template_payload(template)
    btn_comp = [c for c in payload["components"] if c["type"] == "BUTTONS"]
    assert len(btn_comp) == 1
    assert btn_comp[0]["buttons"][0]["type"] == "URL"


def test_build_payload_variables_example():
    template = {
        "name": "vars_test",
        "language": "en",
        "category": "utility",
        "header": {"type": "none"},
        "body": "Hi {{1}}, your order from {{2}} is ready.",
        "footer": "",
        "buttons": [],
        "variables": ["name", "company"],
    }
    payload = _build_meta_template_payload(template)
    body_comp = [c for c in payload["components"] if c["type"] == "BODY"][0]
    assert "example" in body_comp
    assert len(body_comp["example"]["body_text"][0]) == 2


def test_is_meta_configured_returns_false_without_env():
    import os
    old = os.environ.pop("WA_BUSINESS_ACCOUNT_ID", None)
    try:
        assert is_meta_configured() is False
    finally:
        if old:
            os.environ["WA_BUSINESS_ACCOUNT_ID"] = old
