"""
Unit tests for core/onboarding.py

Tests: step tracking, progress calculation, completion,
       skip logic, readiness checklist, auto-detect.
"""

import pytest


class TestOnboardingSteps:
    def test_initial_state_not_complete(self, tmp_data_dir):
        from onboarding import get_onboarding_state
        state = get_onboarding_state("ws_test")
        assert state["is_complete"] is False
        assert state["progress_pct"] == 0

    def test_mark_step_done(self, tmp_data_dir):
        from onboarding import mark_step_done, get_onboarding_state
        mark_step_done("ws_test", "account_created")
        state = get_onboarding_state("ws_test")
        assert state["steps"]["account_created"]["done"] is True
        assert state["progress_pct"] > 0

    def test_invalid_step_rejected(self, tmp_data_dir):
        from onboarding import mark_step_done
        with pytest.raises(ValueError):
            mark_step_done("ws_test", "nonexistent_step")

    def test_skip_optional_step(self, tmp_data_dir):
        from onboarding import skip_step, get_onboarding_state
        skip_step("ws_test", "whatsapp_connect")
        state = get_onboarding_state("ws_test")
        assert state["steps"]["whatsapp_connect"]["skipped"] is True

    def test_cannot_skip_required_step(self, tmp_data_dir):
        from onboarding import skip_step
        with pytest.raises(ValueError):
            skip_step("ws_test", "knowledge_base")

    def test_complete_all_required_steps(self, tmp_data_dir):
        from onboarding import mark_step_done, get_onboarding_state, REQUIRED_STEPS
        for sid in REQUIRED_STEPS:
            mark_step_done("ws_test", sid)
        state = get_onboarding_state("ws_test")
        assert state["is_complete"] is True
        assert state["progress_pct"] == 100
        assert state["completed_at"] is not None

    def test_next_step_correct(self, tmp_data_dir):
        from onboarding import get_onboarding_state, mark_step_done
        state = get_onboarding_state("ws_test")
        assert state["next_step"] == "account_created"
        mark_step_done("ws_test", "account_created")
        state2 = get_onboarding_state("ws_test")
        assert state2["next_step"] == "business_info"

    def test_reset_onboarding(self, tmp_data_dir):
        from onboarding import mark_step_done, reset_onboarding, get_onboarding_state
        mark_step_done("ws_test", "account_created")
        reset_onboarding("ws_test")
        state = get_onboarding_state("ws_test")
        assert state["is_complete"] is False
        assert state["steps"]["account_created"]["done"] is False

    def test_steps_have_order(self, tmp_data_dir):
        from onboarding import get_onboarding_state
        state = get_onboarding_state("ws_test")
        orders = [s["order"] for s in state["steps_list"]]
        assert orders == sorted(orders)

    def test_steps_list_has_all_steps(self, tmp_data_dir):
        from onboarding import get_onboarding_state, ONBOARDING_STEPS
        state = get_onboarding_state("ws_test")
        assert len(state["steps_list"]) == len(ONBOARDING_STEPS)

    def test_workspace_isolation(self, tmp_data_dir):
        from onboarding import mark_step_done, get_onboarding_state
        mark_step_done("ws_a", "account_created")
        state_b = get_onboarding_state("ws_b")
        assert state_b["steps"]["account_created"]["done"] is False

    def test_partial_completion_pct(self, tmp_data_dir):
        from onboarding import mark_step_done, get_onboarding_state, REQUIRED_STEPS
        steps = list(REQUIRED_STEPS)
        # Mark half
        half = steps[:len(steps) // 2]
        for sid in half:
            mark_step_done("ws_test", sid)
        state = get_onboarding_state("ws_test")
        assert 0 < state["progress_pct"] < 100


class TestReadinessChecklist:
    def test_checklist_has_required_keys(self, tmp_data_dir):
        from onboarding import get_readiness_checklist
        checklist = get_readiness_checklist("ws_test")
        assert "ready" in checklist
        assert "checks" in checklist
        assert "score" in checklist
        assert "passed" in checklist

    def test_each_check_has_required_fields(self, tmp_data_dir):
        from onboarding import get_readiness_checklist
        checklist = get_readiness_checklist("ws_test")
        for check in checklist["checks"]:
            assert "id" in check
            assert "label" in check
            assert "passed" in check
            assert "critical" in check
            assert "fix" in check

    def test_llm_check_passes_with_env_key(self, tmp_data_dir, monkeypatch):
        import os
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
        from onboarding import get_readiness_checklist
        checklist = get_readiness_checklist("ws_test")
        llm_check = next(c for c in checklist["checks"] if c["id"] == "llm_provider")
        assert llm_check["passed"] is True

    def test_score_is_percentage(self, tmp_data_dir):
        from onboarding import get_readiness_checklist
        checklist = get_readiness_checklist("ws_test")
        assert 0 <= checklist["score"] <= 100
