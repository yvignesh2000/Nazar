"""
Unit tests for core/optout_manager.py

Tests: keyword detection, opt-out recording, opt-in re-subscription,
       can_message guard, contact profile sync.
"""

import pytest
from pathlib import Path


class TestStopKeywordDetection:
    def test_stop_exact(self):
        from optout_manager import is_stop_message
        assert is_stop_message("STOP") is True
        assert is_stop_message("stop") is True
        assert is_stop_message("Stop") is True

    def test_stop_variations(self):
        from optout_manager import is_stop_message
        assert is_stop_message("unsubscribe") is True
        assert is_stop_message("opt out") is True
        assert is_stop_message("opt-out") is True
        assert is_stop_message("please stop messaging me") is True
        assert is_stop_message("remove me from your list") is True
        assert is_stop_message("do not contact me") is True

    def test_normal_messages_not_stop(self):
        from optout_manager import is_stop_message
        assert is_stop_message("Hello there") is False
        assert is_stop_message("What are your prices?") is False
        assert is_stop_message("I want to buy your product") is False
        assert is_stop_message("Stop being so helpful") is False  # "stop" mid-sentence not a STOP command

    def test_empty_message(self):
        from optout_manager import is_stop_message
        assert is_stop_message("") is False


class TestStartKeywordDetection:
    def test_start_exact(self):
        from optout_manager import is_start_message
        assert is_start_message("START") is True
        assert is_start_message("start") is True

    def test_start_variations(self):
        from optout_manager import is_start_message
        assert is_start_message("subscribe") is True
        assert is_start_message("opt in") is True
        assert is_start_message("yes") is True

    def test_normal_messages_not_start(self):
        from optout_manager import is_start_message
        assert is_start_message("Hello") is False
        assert is_start_message("Tell me more") is False


class TestOptOutFlow:
    def test_record_optout(self, tmp_data_dir):
        import optout_manager
        from unittest.mock import patch
        with patch.object(optout_manager, "DATA_DIR", tmp_data_dir):
            from optout_manager import record_optout, is_opted_out
            record = record_optout("+919876543210", reason="STOP message", message="STOP")
            assert record["opted_out"] is True
            assert record["phone"] == "+919876543210"

    def test_is_opted_out_after_record(self, tmp_data_dir):
        import optout_manager
        with patch_data_dir(optout_manager, tmp_data_dir):
            from optout_manager import record_optout, is_opted_out
            record_optout("+919876543210", reason="STOP")
            assert is_opted_out("+919876543210") is True

    def test_unknown_phone_not_opted_out(self, tmp_data_dir):
        import optout_manager
        with patch_data_dir(optout_manager, tmp_data_dir):
            from optout_manager import is_opted_out
            assert is_opted_out("+910000000000") is False

    def test_can_message_before_optout(self, tmp_data_dir):
        import optout_manager
        with patch_data_dir(optout_manager, tmp_data_dir):
            from optout_manager import can_message
            assert can_message("+919876543210") is True

    def test_cannot_message_after_optout(self, tmp_data_dir):
        import optout_manager
        with patch_data_dir(optout_manager, tmp_data_dir):
            from optout_manager import record_optout, can_message
            record_optout("+919876543210", reason="STOP")
            assert can_message("+919876543210") is False

    def test_optin_resets_optout(self, tmp_data_dir):
        import optout_manager
        with patch_data_dir(optout_manager, tmp_data_dir):
            from optout_manager import record_optout, record_optin, is_opted_out, can_message
            record_optout("+919876543210", reason="STOP")
            assert is_opted_out("+919876543210") is True
            record_optin("+919876543210")
            assert is_opted_out("+919876543210") is False
            assert can_message("+919876543210") is True

    def test_list_optouts(self, tmp_data_dir):
        import optout_manager
        with patch_data_dir(optout_manager, tmp_data_dir):
            from optout_manager import record_optout, list_optouts
            record_optout("+911111111111", reason="STOP")
            record_optout("+912222222222", reason="unsubscribe")
            optouts = list_optouts()
            assert len(optouts) == 2

    def test_get_optout_record(self, tmp_data_dir):
        import optout_manager
        with patch_data_dir(optout_manager, tmp_data_dir):
            from optout_manager import record_optout, get_optout_record
            record_optout("+919876543210", reason="STOP", message="STOP")
            record = get_optout_record("+919876543210")
            assert record is not None
            assert record["reason"] == "STOP"

    def test_optout_count(self, tmp_data_dir):
        import optout_manager
        with patch_data_dir(optout_manager, tmp_data_dir):
            from optout_manager import record_optout, get_optout_count
            assert get_optout_count() == 0
            record_optout("+911111111111", reason="STOP")
            assert get_optout_count() == 1


# Helper to patch DATA_DIR in optout_manager
from contextlib import contextmanager
from unittest.mock import patch

@contextmanager
def patch_data_dir(module, tmp_dir):
    with patch.object(module, "DATA_DIR", tmp_dir):
        yield
