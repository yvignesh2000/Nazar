"""Tests for contact groups module."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from database import init_db, reset_db, get_db
from contact_manager import create_contact
from contact_groups import (
    create_group, list_groups, get_group, update_group, delete_group,
    add_members, remove_members, get_group_members, get_contact_groups,
    get_contacts_by_group_ids,
)


@pytest.fixture(autouse=True)
def setup_db(tmp_path):
    init_db(tmp_path / "test.db")
    yield
    reset_db()


@pytest.fixture
def sample_contacts():
    c1 = create_contact("Alice", "+910001", company="Acme")
    c2 = create_contact("Bob", "+910002", company="Beta")
    c3 = create_contact("Charlie", "+910003", company="Gamma")
    return [c1, c2, c3]


class TestGroupCRUD:
    def test_create_group(self):
        g = create_group("VIP Customers", description="High value", color="#ef4444")
        assert g["id"].startswith("grp_")
        assert g["name"] == "VIP Customers"
        assert g["description"] == "High value"
        assert g["color"] == "#ef4444"
        assert g["member_count"] == 0

    def test_list_groups(self):
        create_group("Group A")
        create_group("Group B")
        groups = list_groups()
        assert len(groups) == 2
        names = [g["name"] for g in groups]
        assert "Group A" in names
        assert "Group B" in names

    def test_get_group(self):
        g = create_group("Test Group")
        found = get_group(g["id"])
        assert found is not None
        assert found["name"] == "Test Group"

    def test_get_nonexistent_group(self):
        assert get_group("grp_nonexistent") is None

    def test_update_group(self):
        g = create_group("Old Name")
        updated = update_group(g["id"], name="New Name", color="#22c55e")
        assert updated["name"] == "New Name"
        assert updated["color"] == "#22c55e"

    def test_delete_group(self):
        g = create_group("To Delete")
        assert delete_group(g["id"]) is True
        assert get_group(g["id"]) is None

    def test_delete_nonexistent(self):
        assert delete_group("grp_fake") is False


class TestGroupMembership:
    def test_add_members(self, sample_contacts):
        g = create_group("Team Alpha")
        ids = [c["contact_id"] for c in sample_contacts[:2]]
        added = add_members(g["id"], ids)
        assert added == 2

        # Check member count
        refreshed = get_group(g["id"])
        assert refreshed["member_count"] == 2

    def test_remove_members(self, sample_contacts):
        g = create_group("Team Beta")
        ids = [c["contact_id"] for c in sample_contacts]
        add_members(g["id"], ids)

        removed = remove_members(g["id"], [ids[0]])
        assert removed == 1

        refreshed = get_group(g["id"])
        assert refreshed["member_count"] == 2

    def test_get_group_members(self, sample_contacts):
        g = create_group("Team Gamma")
        ids = [c["contact_id"] for c in sample_contacts]
        add_members(g["id"], ids)

        members = get_group_members(g["id"])
        assert len(members) == 3

    def test_get_contact_groups(self, sample_contacts):
        g1 = create_group("Group A")
        g2 = create_group("Group B")
        cid = sample_contacts[0]["contact_id"]
        add_members(g1["id"], [cid])
        add_members(g2["id"], [cid])

        groups = get_contact_groups(cid)
        assert len(groups) == 2

    def test_get_contacts_by_group_ids(self, sample_contacts):
        g1 = create_group("G1")
        g2 = create_group("G2")
        add_members(g1["id"], [sample_contacts[0]["contact_id"]])
        add_members(g2["id"], [sample_contacts[1]["contact_id"], sample_contacts[0]["contact_id"]])

        # Get unique contacts across both groups
        contact_ids = get_contacts_by_group_ids([g1["id"], g2["id"]])
        assert len(contact_ids) == 2  # Alice appears in both but should be deduplicated

    def test_add_duplicate_member(self, sample_contacts):
        g = create_group("Dedup Test")
        cid = sample_contacts[0]["contact_id"]
        add_members(g["id"], [cid])
        add_members(g["id"], [cid])  # Should be ignored (INSERT OR IGNORE)

        refreshed = get_group(g["id"])
        assert refreshed["member_count"] == 1

    def test_delete_group_cascades_members(self, sample_contacts):
        g = create_group("Cascade Test")
        add_members(g["id"], [c["contact_id"] for c in sample_contacts])
        delete_group(g["id"])

        # Members should be gone
        with get_db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM contact_group_members WHERE group_id = ?",
                (g["id"],)
            ).fetchone()[0]
        assert count == 0
