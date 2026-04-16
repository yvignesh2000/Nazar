"""Tests for AI pipeline stage classifier."""

import pytest
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from pipeline_classifier import classify_contact_stage, should_classify, PIPELINE_STAGES


class TestShouldClassify:
    def test_new_contact_should_classify(self):
        contact = {"pipeline_stage": "New", "manual_stage_override": False}
        assert should_classify(contact) is True

    def test_manual_override_blocks_classification(self):
        contact = {"pipeline_stage": "Qualified", "manual_stage_override": True}
        assert should_classify(contact) is False

    def test_won_stage_blocks_classification(self):
        contact = {"pipeline_stage": "Won", "manual_stage_override": False}
        assert should_classify(contact) is False

    def test_lost_stage_blocks_classification(self):
        contact = {"pipeline_stage": "Lost", "manual_stage_override": False}
        assert should_classify(contact) is False

    def test_negotiation_allows_classification(self):
        contact = {"pipeline_stage": "Negotiation", "manual_stage_override": False}
        assert should_classify(contact) is True

    def test_missing_override_flag_defaults_to_classify(self):
        contact = {"pipeline_stage": "New"}
        assert should_classify(contact) is True


class TestClassifyContactStage:
    @pytest.mark.asyncio
    async def test_classify_returns_valid_stage(self):
        async def mock_llm(messages):
            return json.dumps({"stage": "Qualified", "confidence": 0.85, "reason": "Customer asked about features"})

        contact = {"pipeline_stage": "New", "name": "Test", "deal_value": 0, "lead_score": 10}
        messages = [
            {"direction": "inbound", "content": "Hi, can you tell me about your product?"},
            {"direction": "outbound", "content": "Sure! We offer..."},
            {"direction": "inbound", "content": "That sounds great. What are the key features?"},
        ]

        result = await classify_contact_stage(contact, messages, mock_llm)
        assert result is not None
        assert result["stage"] == "Qualified"
        assert result["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_classify_returns_none_on_low_confidence(self):
        async def mock_llm(messages):
            return json.dumps({"stage": "Proposal", "confidence": 0.3, "reason": "Not sure"})

        contact = {"pipeline_stage": "New", "name": "Test", "deal_value": 0, "lead_score": 0}
        messages = [{"direction": "inbound", "content": "Hello"}]

        result = await classify_contact_stage(contact, messages, mock_llm)
        assert result is None  # Below 0.6 threshold

    @pytest.mark.asyncio
    async def test_classify_returns_none_on_invalid_stage(self):
        async def mock_llm(messages):
            return json.dumps({"stage": "InvalidStage", "confidence": 0.9, "reason": "Test"})

        contact = {"pipeline_stage": "New", "name": "Test", "deal_value": 0, "lead_score": 0}
        messages = [{"direction": "inbound", "content": "Hello"}]

        result = await classify_contact_stage(contact, messages, mock_llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_classify_returns_none_on_bad_json(self):
        async def mock_llm(messages):
            return "This is not JSON"

        contact = {"pipeline_stage": "New", "name": "Test", "deal_value": 0, "lead_score": 0}
        messages = [{"direction": "inbound", "content": "Hello"}]

        result = await classify_contact_stage(contact, messages, mock_llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_classify_returns_none_on_empty_messages(self):
        async def mock_llm(messages):
            return json.dumps({"stage": "New", "confidence": 0.9, "reason": "No messages"})

        contact = {"pipeline_stage": "New", "name": "Test", "deal_value": 0, "lead_score": 0}

        result = await classify_contact_stage(contact, [], mock_llm)
        assert result is None  # Empty messages → return None

    @pytest.mark.asyncio
    async def test_classify_handles_markdown_wrapped_json(self):
        async def mock_llm(messages):
            return '```json\n{"stage": "Negotiation", "confidence": 0.8, "reason": "Price discussion"}\n```'

        contact = {"pipeline_stage": "Qualified", "name": "Test", "deal_value": 5000, "lead_score": 50}
        messages = [
            {"direction": "inbound", "content": "What's the best price you can offer?"},
            {"direction": "outbound", "content": "We can offer 10% discount for annual plans"},
        ]

        result = await classify_contact_stage(contact, messages, mock_llm)
        assert result is not None
        assert result["stage"] == "Negotiation"

    @pytest.mark.asyncio
    async def test_classify_handles_llm_exception(self):
        async def mock_llm(messages):
            raise Exception("LLM service unavailable")

        contact = {"pipeline_stage": "New", "name": "Test", "deal_value": 0, "lead_score": 0}
        messages = [{"direction": "inbound", "content": "Hello"}]

        result = await classify_contact_stage(contact, messages, mock_llm)
        assert result is None
