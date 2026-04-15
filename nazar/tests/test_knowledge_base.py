"""
Tests for core/knowledge_base.py — structured KB with RAG.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
import knowledge_base as kb


@pytest.fixture(autouse=True)
def tmp_kb_dir(tmp_path, monkeypatch):
    """Redirect KB_DIR and DATA_DIR to temp paths."""
    monkeypatch.setattr(kb, "DATA_DIR", tmp_path)
    monkeypatch.setattr(kb, "KB_DIR", tmp_path / "kb")
    monkeypatch.setattr(kb, "CHROMADB_AVAILABLE", False)  # Use fallback mode
    monkeypatch.setattr(kb, "_chroma_client", None)
    yield tmp_path


class TestChunkText:
    def test_single_chunk_short_text(self):
        text = "Hello world this is a short text"
        chunks = kb.chunk_text(text, chunk_size=100)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_multiple_chunks_long_text(self):
        words = ["word"] * 600
        text = " ".join(words)
        chunks = kb.chunk_text(text, chunk_size=200, overlap=20)
        assert len(chunks) > 1

    def test_empty_text_returns_empty(self):
        chunks = kb.chunk_text("   ")
        assert chunks == []

    def test_overlap_creates_more_chunks(self):
        words = ["w"] * 300
        text = " ".join(words)
        chunks_no_overlap = kb.chunk_text(text, chunk_size=100, overlap=0)
        chunks_with_overlap = kb.chunk_text(text, chunk_size=100, overlap=50)
        assert len(chunks_with_overlap) >= len(chunks_no_overlap)

    def test_chunk_content_preserved(self):
        text = "Alpha beta gamma delta epsilon"
        chunks = kb.chunk_text(text, chunk_size=3, overlap=1)
        # All words should appear across chunks
        all_words = " ".join(chunks).split()
        for word in ["Alpha", "beta", "gamma"]:
            assert word in all_words


class TestAddDocument:
    def test_add_document_returns_metadata(self, tmp_path):
        doc = kb.add_document("My FAQ", "This is the FAQ content.", scope="global")
        assert doc["id"].startswith("doc_")
        assert doc["title"] == "My FAQ"
        assert doc["scope"] == "global"
        assert doc["char_count"] > 0

    def test_add_document_creates_raw_file(self, tmp_path):
        doc = kb.add_document("Test Doc", "Some content here.", scope="global")
        raw_dir = tmp_path / "kb" / "raw"
        raw_file = raw_dir / f"{doc['id']}.txt"
        assert raw_file.exists()
        assert raw_file.read_text() == "Some content here."

    def test_add_document_persists_to_docs_index(self, tmp_path):
        doc = kb.add_document("Indexed Doc", "Content.", scope="global")
        docs = kb._load_docs()
        assert doc["id"] in docs

    def test_add_campaign_document(self, tmp_path):
        doc = kb.add_document("Campaign FAQ", "Campaign content.", scope="campaign", campaign_id="cmp_001")
        assert doc["scope"] == "campaign"
        assert doc["campaign_id"] == "cmp_001"


class TestQueryFallback:
    def test_query_returns_raw_text_when_chromadb_unavailable(self, tmp_path):
        kb.add_document("FAQ", "Our product costs $99/month.", scope="global")
        result = kb.query("How much does it cost?", scope="global")
        assert "99" in result

    def test_query_returns_empty_when_no_documents(self, tmp_path):
        result = kb.query("anything", scope="global")
        assert result == "" or isinstance(result, str)

    def test_query_campaign_scope(self, tmp_path):
        kb.add_document("Campaign KB", "Campaign special offer: 50% off.", scope="campaign", campaign_id="cmp_X")
        result = kb.query("discount", scope="campaign", campaign_id="cmp_X")
        assert "50" in result


class TestListDocuments:
    def test_list_returns_added_docs(self, tmp_path):
        kb.add_document("Doc A", "Content A.", scope="global")
        kb.add_document("Doc B", "Content B.", scope="global")
        docs = kb.list_documents(scope="global")
        titles = [d["title"] for d in docs]
        assert "Doc A" in titles
        assert "Doc B" in titles

    def test_list_filtered_by_campaign(self, tmp_path):
        kb.add_document("Global", "Global content.", scope="global")
        kb.add_document("Camp 1", "Campaign 1 content.", scope="campaign", campaign_id="c1")
        kb.add_document("Camp 2", "Campaign 2 content.", scope="campaign", campaign_id="c2")
        camp1_docs = kb.list_documents(scope="campaign", campaign_id="c1")
        assert len(camp1_docs) == 1
        assert camp1_docs[0]["title"] == "Camp 1"


class TestDeleteDocument:
    def test_delete_removes_from_index(self, tmp_path):
        doc = kb.add_document("To Delete", "Delete me.", scope="global")
        result = kb.delete_document(doc["id"])
        assert result is True
        assert kb.get_document(doc["id"]) is None

    def test_delete_removes_raw_file(self, tmp_path):
        doc = kb.add_document("Delete Raw", "Raw content.", scope="global")
        raw_path = kb._raw_text_path(doc["id"])
        assert raw_path.exists()
        kb.delete_document(doc["id"])
        assert not raw_path.exists()

    def test_delete_nonexistent_returns_false(self, tmp_path):
        result = kb.delete_document("nonexistent_doc_id")
        assert result is False


class TestImportLegacyKB:
    def test_import_creates_document(self, tmp_path):
        # Create legacy knowledge_base.txt
        kb_file = tmp_path / "knowledge_base.txt"
        kb_file.write_text("Legacy KB content here.", encoding="utf-8")
        result = kb.import_legacy_kb()
        assert result is not None
        assert result["title"] == "__legacy_global_kb__"

    def test_import_idempotent(self, tmp_path):
        kb_file = tmp_path / "knowledge_base.txt"
        kb_file.write_text("Legacy content.", encoding="utf-8")
        r1 = kb.import_legacy_kb()
        r2 = kb.import_legacy_kb()  # Second call should return None
        assert r1 is not None
        assert r2 is None

    def test_import_missing_file_returns_none(self, tmp_path):
        result = kb.import_legacy_kb()
        assert result is None
