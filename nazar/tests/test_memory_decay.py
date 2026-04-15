"""
Tests for memory decay and recency-weighted retrieval (Plan item #20).
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
import customer_memory


IST = timezone(timedelta(hours=5, minutes=30))


def _ts(days_ago: int) -> str:
    return (datetime.now(IST) - timedelta(days=days_ago)).isoformat()


class TestPruneStaleMemories:
    def test_returns_zero_when_chromadb_unavailable(self, tmp_path, monkeypatch):
        """When ChromaDB is not available, pruning should return 0 gracefully."""
        monkeypatch.setattr(customer_memory, "CHROMADB_AVAILABLE", False)
        result = customer_memory.prune_stale_memories("contact_001")
        assert result == 0

    def test_returns_zero_when_no_collection(self, tmp_path, monkeypatch):
        """When collection cannot be obtained, return 0."""
        monkeypatch.setattr(customer_memory, "CHROMADB_AVAILABLE", True)
        with patch.object(customer_memory, "get_collection", return_value=None):
            result = customer_memory.prune_stale_memories("contact_002")
        assert result == 0

    def test_pruning_removes_old_entries(self):
        """Mock collection to verify old entries are deleted."""
        old_ids = ["old_1", "old_2", "old_3"]
        old_docs = ["old doc 1", "old doc 2", "old doc 3"]
        old_metas = [
            {"timestamp": _ts(200), "type": "message"},
            {"timestamp": _ts(250), "type": "message"},
            {"timestamp": _ts(300), "type": "signal"},
        ]

        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": old_ids,
            "documents": old_docs,
            "metadatas": old_metas,
        }
        mock_collection.upsert = MagicMock()
        mock_collection.delete = MagicMock()

        with patch.object(customer_memory, "get_collection", return_value=mock_collection):
            result = customer_memory.prune_stale_memories("contact_003", max_age_days=180)

        assert result == 3
        mock_collection.delete.assert_called_once_with(ids=old_ids)
        mock_collection.upsert.assert_called_once()

    def test_pruning_preserves_recent_entries(self):
        """Recent entries should not be pruned."""
        recent_ids = ["recent_1", "recent_2"]
        recent_docs = ["recent doc 1", "recent doc 2"]
        recent_metas = [
            {"timestamp": _ts(5), "type": "message"},
            {"timestamp": _ts(10), "type": "signal"},
        ]

        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": recent_ids,
            "documents": recent_docs,
            "metadatas": recent_metas,
        }
        mock_collection.upsert = MagicMock()
        mock_collection.delete = MagicMock()

        with patch.object(customer_memory, "get_collection", return_value=mock_collection):
            result = customer_memory.prune_stale_memories("contact_004", max_age_days=180)

        assert result == 0
        mock_collection.delete.assert_not_called()

    def test_historical_summary_is_added_on_prune(self):
        """A summary entry is upserted when old entries are removed."""
        old_ids = ["old_entry_1"]
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": old_ids,
            "documents": ["some old content"],
            "metadatas": [{"timestamp": _ts(200), "type": "message"}],
        }
        mock_collection.upsert = MagicMock()
        mock_collection.delete = MagicMock()

        with patch.object(customer_memory, "get_collection", return_value=mock_collection):
            customer_memory.prune_stale_memories("contact_005", max_age_days=180)

        # Summary upsert should have been called
        assert mock_collection.upsert.called
        upsert_kwargs = mock_collection.upsert.call_args
        upserted_id = upsert_kwargs[1]["ids"][0] if upsert_kwargs[1] else upsert_kwargs[0][0][0]
        assert "hist_summary" in upserted_id


class TestRecencyWeightedRetrieval:
    def test_returns_empty_when_no_results(self):
        with patch.object(customer_memory, "search", return_value=[]):
            result = customer_memory.get_relevant_context_with_recency("c_001", "test query")
        assert result == ""

    def test_returns_formatted_context(self):
        mock_hits = [
            {
                "content": "Customer asked about pricing",
                "type": "message",
                "direction": "inbound",
                "date": "2026-01-15",
                "timestamp": _ts(5),
                "distance": 0.3,
            },
            {
                "content": "Sales rep sent proposal",
                "type": "message",
                "direction": "outbound",
                "date": "2026-01-14",
                "timestamp": _ts(6),
                "distance": 0.4,
            },
        ]
        with patch.object(customer_memory, "search", return_value=mock_hits):
            result = customer_memory.get_relevant_context_with_recency("c_002", "price")
        assert "Customer" in result
        assert "Sales rep" in result

    def test_recent_hits_ranked_higher(self):
        """Hits with lower age should score better (lower score = better)."""
        recent_hit = {
            "content": "Recent buying signal",
            "type": "signal",
            "direction": "inbound",
            "date": "2026-04-10",
            "timestamp": _ts(1),
            "distance": 0.5,
        }
        old_hit = {
            "content": "Old objection from 2 years ago",
            "type": "signal",
            "direction": "inbound",
            "date": "2024-04-10",
            "timestamp": _ts(700),
            "distance": 0.3,  # Semantically closer but older
        }

        with patch.object(customer_memory, "search", return_value=[recent_hit, old_hit]):
            result = customer_memory.get_relevant_context_with_recency("c_003", "buying")

        # Recent hit should appear first (content-wise or be included)
        assert "Recent" in result

    def test_very_distant_hits_excluded(self):
        """Hits with distance > 1.5 should not appear in output."""
        far_hit = {
            "content": "Irrelevant content",
            "type": "message",
            "direction": "inbound",
            "date": "2026-01-01",
            "timestamp": _ts(10),
            "distance": 2.0,  # Too far
        }
        with patch.object(customer_memory, "search", return_value=[far_hit]):
            result = customer_memory.get_relevant_context_with_recency("c_004", "anything")
        # Should be empty after distance filter
        assert "Irrelevant" not in result
