"""
Unit tests for core/template_manager.py

Tests: CRUD, rendering, suggestions, stats, validation.
"""

import pytest
import uuid


class TestTemplateList:
    def test_list_returns_defaults(self, tmp_data_dir):
        """Default templates are initialised when none exist."""
        from template_manager import list_templates
        templates = list_templates()
        assert len(templates) > 0

    def test_filter_by_category(self, tmp_data_dir):
        from template_manager import list_templates
        utility = list_templates(category="utility")
        assert all(t["category"] == "utility" for t in utility)

    def test_filter_by_status(self, tmp_data_dir):
        from template_manager import list_templates
        approved = list_templates(status="approved")
        assert all(t["approval_status"] == "approved" for t in approved)


class TestTemplateCRUD:
    def test_create_template(self, tmp_data_dir):
        from template_manager import create_template, get_template
        name = f"test_tpl_{uuid.uuid4().hex[:6]}"
        tpl = create_template(name=name, body="Hello {{1}}!", category="utility")
        assert tpl["id"].startswith("tpl_")
        assert tpl["name"] == name
        assert tpl["approval_status"] == "pending"

    def test_duplicate_name_rejected(self, tmp_data_dir):
        from template_manager import create_template
        name = f"dupe_{uuid.uuid4().hex[:6]}"
        create_template(name=name, body="Hello", category="utility")
        with pytest.raises(ValueError, match="already exists"):
            create_template(name=name, body="Different body", category="utility")

    def test_invalid_category_rejected(self, tmp_data_dir):
        from template_manager import create_template
        with pytest.raises(ValueError, match="Invalid category"):
            create_template(name="test_cat", body="Hello", category="unknown_cat")

    def test_too_many_buttons_rejected(self, tmp_data_dir):
        from template_manager import create_template
        with pytest.raises(ValueError, match="Maximum 3 buttons"):
            create_template(
                name="test_btn",
                body="Hello",
                category="utility",
                buttons=[{"type": "quick_reply", "text": str(i)} for i in range(4)],
            )

    def test_get_template_by_id(self, tmp_data_dir):
        from template_manager import create_template, get_template
        name = f"get_{uuid.uuid4().hex[:6]}"
        tpl = create_template(name=name, body="Body", category="utility")
        fetched = get_template(tpl["id"])
        assert fetched is not None
        assert fetched["name"] == name

    def test_get_template_not_found(self, tmp_data_dir):
        from template_manager import get_template
        assert get_template("tpl_nonexistent") is None

    def test_get_template_by_name(self, tmp_data_dir):
        from template_manager import create_template, get_template_by_name
        name = f"byname_{uuid.uuid4().hex[:6]}"
        create_template(name=name, body="Body", category="utility")
        fetched = get_template_by_name(name)
        assert fetched is not None

    def test_update_template(self, tmp_data_dir):
        from template_manager import create_template, update_template
        name = f"upd_{uuid.uuid4().hex[:6]}"
        tpl = create_template(name=name, body="Old body", category="utility")
        updated = update_template(tpl["id"], body="New body", approval_status="approved")
        assert updated["body"] == "New body"
        assert updated["approval_status"] == "approved"

    def test_update_nonexistent_raises(self, tmp_data_dir):
        from template_manager import update_template
        with pytest.raises(ValueError, match="not found"):
            update_template("tpl_nonexistent", body="X")

    def test_delete_template(self, tmp_data_dir):
        from template_manager import create_template, delete_template, get_template
        name = f"del_{uuid.uuid4().hex[:6]}"
        tpl = create_template(name=name, body="Body", category="utility")
        delete_template(tpl["id"])
        assert get_template(tpl["id"]) is None

    def test_increment_usage(self, tmp_data_dir):
        from template_manager import create_template, increment_usage, get_template
        name = f"usage_{uuid.uuid4().hex[:6]}"
        tpl = create_template(name=name, body="Body", category="utility")
        increment_usage(tpl["id"])
        increment_usage(tpl["id"])
        fetched = get_template(tpl["id"])
        assert fetched["usage_count"] == 2


class TestTemplateRendering:
    def test_render_with_name(self, tmp_data_dir):
        from template_manager import create_template, render_template
        name = f"render_{uuid.uuid4().hex[:6]}"
        tpl = create_template(
            name=name,
            body="Hi {{1}}, welcome!",
            category="utility",
            variables=["name"],
        )
        contact = {"name": "Alice", "phone": "+91999"}
        rendered = render_template(tpl, contact)
        assert "Alice" in rendered
        assert "{{1}}" not in rendered

    def test_render_multiple_variables(self, tmp_data_dir):
        from template_manager import create_template, render_template
        name = f"render2_{uuid.uuid4().hex[:6]}"
        tpl = create_template(
            name=name,
            body="Hi {{1}} from {{2}}!",
            category="utility",
            variables=["name", "company"],
        )
        contact = {"name": "Bob", "company": "Acme Corp", "phone": "+91999"}
        rendered = render_template(tpl, contact)
        assert "Bob" in rendered
        assert "Acme Corp" in rendered

    def test_render_uses_fallback_for_missing_name(self, tmp_data_dir):
        from template_manager import create_template, render_template
        name = f"render3_{uuid.uuid4().hex[:6]}"
        tpl = create_template(
            name=name,
            body="Hi {{1}}!",
            category="utility",
            variables=["name"],
        )
        contact = {"name": "", "phone": "+91999"}
        rendered = render_template(tpl, contact)
        assert "there" in rendered  # fallback

    def test_render_no_variables(self, tmp_data_dir):
        from template_manager import create_template, render_template
        name = f"render4_{uuid.uuid4().hex[:6]}"
        tpl = create_template(name=name, body="Hello World!", category="utility")
        rendered = render_template(tpl, {"name": "Alice"})
        assert rendered == "Hello World!"


class TestTemplateSuggestions:
    def test_suggest_for_new_lead(self, tmp_data_dir):
        from template_manager import suggest_template
        contact = {"pipeline_stage": "New"}
        suggestion = suggest_template(contact)
        # Should suggest the welcome template
        assert suggestion is not None
        assert suggestion.get("approval_status") == "approved"

    def test_suggest_for_qualified(self, tmp_data_dir):
        from template_manager import suggest_template
        contact = {"pipeline_stage": "Qualified"}
        suggestion = suggest_template(contact)
        assert suggestion is not None

    def test_suggest_for_won(self, tmp_data_dir):
        from template_manager import suggest_template
        contact = {"pipeline_stage": "Won"}
        suggestion = suggest_template(contact)
        assert suggestion is not None


class TestTemplateStats:
    def test_stats_shape(self, tmp_data_dir):
        from template_manager import get_template_stats
        stats = get_template_stats()
        assert "total" in stats
        assert "approved" in stats
        assert "pending" in stats
        assert "categories" in stats

    def test_stats_count_correctly(self, tmp_data_dir):
        from template_manager import create_template, get_template_stats
        initial_stats = get_template_stats()
        name = f"stats_{uuid.uuid4().hex[:6]}"
        create_template(name=name, body="Body", category="utility")
        stats = get_template_stats()
        assert stats["total"] == initial_stats["total"] + 1
        assert stats["pending"] == initial_stats["pending"] + 1
