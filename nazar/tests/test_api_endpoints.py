"""
Integration tests for server.py API endpoints.

Tests: auth, contacts, conversations, pipeline, handoffs,
       broadcasts, templates, analytics, billing, onboarding.

Uses FastAPI TestClient with mocked LLM and isolated data dir.
"""

import json
import pytest
from unittest.mock import patch, AsyncMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def post(client, path, json_body=None, headers=None):
    h = {"X-Nazar-Key": "test_key_abc123", **(headers or {})}
    return client.post(path, json=json_body, headers=h)

def get(client, path, params=None, headers=None):
    h = {"X-Nazar-Key": "test_key_abc123", **(headers or {})}
    return client.get(path, params=params, headers=h)

def patch_req(client, path, json_body=None, headers=None):
    h = {"X-Nazar-Key": "test_key_abc123", **(headers or {})}
    return client.patch(path, json=json_body, headers=h)

def delete(client, path, headers=None):
    h = {"X-Nazar-Key": "test_key_abc123", **(headers or {})}
    return client.delete(path, headers=h)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_endpoint(self, api_client):
        r = api_client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] in ("ok", "degraded")
        assert data["service"] == "nazar"
        assert "checks" in data
        assert "timestamp" in data


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

class TestAuthEndpoints:
    def test_unauthorized_without_key(self, api_client):
        r = api_client.get("/api/overview")
        assert r.status_code == 401

    def test_authorized_with_key(self, api_client):
        r = get(api_client, "/api/overview")
        assert r.status_code == 200

    def test_auth_me_endpoint(self, api_client):
        r = get(api_client, "/api/auth/me")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Contact endpoints
# ---------------------------------------------------------------------------

class TestContactEndpoints:
    def test_create_contact(self, api_client):
        r = post(api_client, "/api/contacts", {
            "name": "Test User",
            "phone": "+919876543210",
        })
        assert r.status_code == 200
        assert r.json()["contact"]["name"] == "Test User"

    def test_create_contact_missing_phone(self, api_client):
        r = post(api_client, "/api/contacts", {"name": "No Phone"})
        assert r.status_code == 400

    def test_list_contacts_empty(self, api_client):
        r = get(api_client, "/api/contacts")
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_list_contacts_after_create(self, api_client):
        post(api_client, "/api/contacts", {"name": "A", "phone": "+911111111111"})
        r = get(api_client, "/api/contacts")
        assert r.json()["total"] == 1

    def test_get_contact_by_id(self, api_client):
        resp = post(api_client, "/api/contacts", {"name": "Bob", "phone": "+912222222222"})
        contact_id = resp.json()["contact"]["contact_id"]
        r = get(api_client, f"/api/contacts/{contact_id}")
        assert r.status_code == 200
        assert r.json()["contact"]["name"] == "Bob"

    def test_get_contact_not_found(self, api_client):
        r = get(api_client, "/api/contacts/nonexistent_id")
        assert r.status_code == 404

    def test_update_contact(self, api_client):
        resp = post(api_client, "/api/contacts", {"name": "C", "phone": "+913333333333"})
        contact_id = resp.json()["contact"]["contact_id"]
        r = patch_req(api_client, f"/api/contacts/{contact_id}", {"deal_value": 50000})
        assert r.status_code == 200
        assert r.json()["contact"]["deal_value"] == 50000

    def test_delete_contact(self, api_client):
        resp = post(api_client, "/api/contacts", {"name": "D", "phone": "+914444444444"})
        contact_id = resp.json()["contact"]["contact_id"]
        r = delete(api_client, f"/api/contacts/{contact_id}")
        assert r.status_code == 200
        # Verify deleted
        r2 = get(api_client, f"/api/contacts/{contact_id}")
        assert r2.status_code == 404

    def test_duplicate_contact_rejected(self, api_client):
        post(api_client, "/api/contacts", {"name": "E", "phone": "+915555555555"})
        r = post(api_client, "/api/contacts", {"name": "E2", "phone": "+915555555555"})
        assert r.status_code == 400

    def test_import_contacts_csv(self, api_client):
        csv = "name,phone\nAlice,+916666666666\nBob,+917777777777"
        r = post(api_client, "/api/contacts/import", {"csv": csv})
        assert r.status_code == 200
        assert r.json()["created"] == 2


# ---------------------------------------------------------------------------
# Pipeline endpoints
# ---------------------------------------------------------------------------

class TestPipelineEndpoints:
    def test_get_pipeline(self, api_client):
        r = get(api_client, "/api/pipeline")
        assert r.status_code == 200
        assert "pipeline" in r.json()
        assert "stages" in r.json()

    def test_move_contact_stage(self, api_client):
        resp = post(api_client, "/api/contacts", {"name": "F", "phone": "+918888888888"})
        contact_id = resp.json()["contact"]["contact_id"]
        r = patch_req(api_client, f"/api/pipeline/{contact_id}/move", {"stage": "Qualified"})
        assert r.status_code == 200
        assert r.json()["contact"]["pipeline_stage"] == "Qualified"

    def test_move_invalid_stage(self, api_client):
        resp = post(api_client, "/api/contacts", {"name": "G", "phone": "+919999999999"})
        contact_id = resp.json()["contact"]["contact_id"]
        r = patch_req(api_client, f"/api/pipeline/{contact_id}/move", {"stage": "Garbage"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Conversations endpoints
# ---------------------------------------------------------------------------

class TestConversationEndpoints:
    def test_list_conversations(self, api_client):
        r = get(api_client, "/api/conversations")
        assert r.status_code == 200
        assert "conversations" in r.json()

    def test_get_conversation(self, api_client):
        resp = post(api_client, "/api/contacts", {"name": "H", "phone": "+910000000001"})
        contact_id = resp.json()["contact"]["contact_id"]
        r = get(api_client, f"/api/conversations/{contact_id}")
        assert r.status_code == 200
        assert "messages" in r.json()

    def test_send_message(self, api_client):
        resp = post(api_client, "/api/contacts", {"name": "I", "phone": "+910000000002"})
        contact_id = resp.json()["contact"]["contact_id"]
        r = post(api_client, f"/api/conversations/{contact_id}/send", {"message": "Hello!"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_send_message_missing_body(self, api_client):
        resp = post(api_client, "/api/contacts", {"name": "J", "phone": "+910000000003"})
        contact_id = resp.json()["contact"]["contact_id"]
        r = post(api_client, f"/api/conversations/{contact_id}/send", {"message": ""})
        assert r.status_code == 400

    def test_handover_to_human(self, api_client):
        resp = post(api_client, "/api/contacts", {"name": "K", "phone": "+910000000004"})
        contact_id = resp.json()["contact"]["contact_id"]
        r = post(api_client, f"/api/conversations/{contact_id}/handover", {"bot_mode": False})
        assert r.status_code == 200
        assert r.json()["bot_mode"] is False


# ---------------------------------------------------------------------------
# Handoff endpoints
# ---------------------------------------------------------------------------

class TestHandoffEndpoints:
    def test_get_handoffs(self, api_client):
        r = get(api_client, "/api/handoffs")
        assert r.status_code == 200
        assert "queue" in r.json()
        assert "stats" in r.json()

    def test_handoff_history(self, api_client):
        r = get(api_client, "/api/handoffs/history")
        assert r.status_code == 200
        assert "history" in r.json()


# ---------------------------------------------------------------------------
# Template endpoints
# ---------------------------------------------------------------------------

class TestTemplateEndpoints:
    def test_list_templates(self, api_client):
        r = get(api_client, "/api/templates")
        assert r.status_code == 200
        assert "templates" in r.json()

    def test_create_template(self, api_client):
        import uuid
        unique_name = f"test_tpl_{uuid.uuid4().hex[:6]}"
        r = post(api_client, "/api/templates", {
            "name": unique_name,
            "body": "Hello {{1}}! This is a test.",
            "category": "utility",
            "variables": ["name"],
        })
        assert r.status_code == 200
        assert r.json()["template"]["name"] == unique_name

    def test_create_duplicate_template_rejected(self, api_client):
        import uuid
        dup_name = f"dup_tpl_{uuid.uuid4().hex[:6]}"
        post(api_client, "/api/templates", {
            "name": dup_name,
            "body": "Body",
            "category": "utility",
        })
        r = post(api_client, "/api/templates", {
            "name": dup_name,
            "body": "Different body",
            "category": "utility",
        })
        assert r.status_code == 400

    def test_delete_template(self, api_client):
        import uuid
        del_name = f"del_tpl_{uuid.uuid4().hex[:6]}"
        resp = post(api_client, "/api/templates", {
            "name": del_name,
            "body": "Delete me",
            "category": "utility",
        })
        tid = resp.json()["template"]["id"]
        r = delete(api_client, f"/api/templates/{tid}")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------

class TestConfigEndpoints:
    def test_get_config(self, api_client):
        r = get(api_client, "/api/config")
        assert r.status_code == 200

    def test_update_config(self, api_client):
        import server
        r = api_client.put(
            "/api/config",
            json={"business_name": "Updated Biz"},
            headers={"X-Nazar-Key": "test_key_abc123"},
        )
        assert r.status_code == 200
        assert r.json().get("business_name") == "Updated Biz"


# ---------------------------------------------------------------------------
# Analytics endpoints
# ---------------------------------------------------------------------------

class TestAnalyticsEndpoints:
    def test_analytics_snapshot(self, api_client):
        r = get(api_client, "/api/analytics")
        assert r.status_code == 200
        data = r.json()
        assert "conversation" in data
        assert "pipeline" in data

    def test_analytics_trend(self, api_client):
        r = get(api_client, "/api/analytics/trend", params={"days": 7})
        assert r.status_code == 200
        assert "trend" in r.json()

    def test_analytics_leads(self, api_client):
        r = get(api_client, "/api/analytics/leads")
        assert r.status_code == 200
        assert "score_bands" in r.json()


# ---------------------------------------------------------------------------
# Billing endpoints
# ---------------------------------------------------------------------------

class TestBillingEndpoints:
    def test_get_plans(self, api_client):
        r = get(api_client, "/api/billing/plans")
        assert r.status_code == 200
        assert "plans" in r.json()
        assert len(r.json()["plans"]) == 4

    def test_get_subscription(self, api_client):
        r = get(api_client, "/api/billing/subscription")
        assert r.status_code == 200
        assert "subscription" in r.json()

    def test_get_usage(self, api_client):
        r = get(api_client, "/api/billing/usage")
        assert r.status_code == 200
        assert "usage" in r.json()

    def test_upgrade_plan(self, api_client):
        r = post(api_client, "/api/billing/upgrade", {"plan_id": "pro"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_upgrade_invalid_plan(self, api_client):
        r = post(api_client, "/api/billing/upgrade", {"plan_id": "invalid"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Onboarding endpoints
# ---------------------------------------------------------------------------

class TestOnboardingEndpoints:
    def test_get_onboarding(self, api_client):
        r = get(api_client, "/api/onboarding")
        assert r.status_code == 200
        assert "is_complete" in r.json()
        assert "steps_list" in r.json()

    def test_mark_step_done(self, api_client):
        r = post(api_client, "/api/onboarding/step/account_created/done")
        assert r.status_code == 200
        assert r.json()["steps"]["account_created"]["done"] is True

    def test_skip_optional_step(self, api_client):
        r = post(api_client, "/api/onboarding/step/whatsapp_connect/skip")
        assert r.status_code == 200

    def test_skip_required_step_rejected(self, api_client):
        r = post(api_client, "/api/onboarding/step/knowledge_base/skip")
        assert r.status_code == 400

    def test_readiness_checklist(self, api_client):
        r = get(api_client, "/api/onboarding/readiness")
        assert r.status_code == 200
        assert "ready" in r.json()
        assert "checks" in r.json()


# ---------------------------------------------------------------------------
# Overview & Activity
# ---------------------------------------------------------------------------

class TestOverviewEndpoints:
    def test_overview(self, api_client):
        r = get(api_client, "/api/overview")
        assert r.status_code == 200
        assert "stats" in r.json()

    def test_activity(self, api_client):
        r = get(api_client, "/api/activity")
        assert r.status_code == 200
        assert "activities" in r.json()


# ---------------------------------------------------------------------------
# Simulate endpoint
# ---------------------------------------------------------------------------

class TestSimulateEndpoint:
    def test_simulate_message(self, api_client):
        # Create a contact first
        resp = post(api_client, "/api/contacts", {"name": "SimUser", "phone": "+910101010101"})
        contact_id = resp.json()["contact"]["contact_id"]

        r = post(api_client, "/api/simulate/message", {
            "contact_id": contact_id,
            "message": "Hello, what are your prices?",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "ai_reply" in data or "mode" in data

    def test_simulate_missing_contact(self, api_client):
        r = post(api_client, "/api/simulate/message", {
            "contact_id": "nonexistent",
            "message": "test",
        })
        assert r.status_code == 404

    def test_simulate_missing_message(self, api_client):
        resp = post(api_client, "/api/contacts", {"name": "S2", "phone": "+910101010102"})
        contact_id = resp.json()["contact"]["contact_id"]
        r = post(api_client, "/api/simulate/message", {
            "contact_id": contact_id,
            "message": "",
        })
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# LLM Health
# ---------------------------------------------------------------------------

class TestLLMHealth:
    def test_llm_health(self, api_client):
        r = get(api_client, "/api/llm/health")
        assert r.status_code == 200
        assert "providers" in r.json()
