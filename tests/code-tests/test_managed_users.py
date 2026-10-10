"""Managed-user policy tests using only synthetic accounts and state."""
from dataclasses import fields

import pytest

import chatlogin as cl


def _service():
    users = cl.ManagedUsers.in_memory("managed-users", max_users=20, max_sessions=20)
    owner = users.bootstrap_owner("owner", "owner-password", "Owner")
    owner_principal = users.authenticate("owner", "owner-password")
    admin = users.create_user(
        owner_principal, "admin", "admin-password", role=cl.Role.ADMIN, display_name="Admin"
    )
    member = users.create_user(owner_principal, "member", "member-password", display_name="Member")
    return users, owner, admin, member


def test_managed_role_matrix_rechecks_live_accounts():
    users, owner, admin, member = _service()
    owner_principal = users.authenticate("owner", "owner-password")
    admin_principal = users.authenticate("admin", "admin-password")
    member_principal = users.authenticate("member", "member-password")

    assert {record.user_id for record in users.list_users(owner_principal)} == {
        owner.user_id,
        admin.user_id,
        member.user_id,
    }
    assert {record.user_id for record in users.list_users(admin_principal)} == {
        admin.user_id,
        member.user_id,
    }
    assert users.current_user(member_principal).user_id == member.user_id
    assert users.get_user(member_principal, member.user_id).username == "member"

    updated = users.update_user(member_principal, member.user_id, display_name="Member Two")
    assert updated.display_name == "Member Two"

    created = users.create_user(admin_principal, "ordinary", "ordinary-password")
    assert created.role is cl.Role.USER
    users.update_user(admin_principal, member.user_id, enabled=False)
    with pytest.raises(cl.ManagedPermissionError):
        users.list_users(member_principal)
    with pytest.raises(cl.ManagedPermissionError):
        users.create_user(admin_principal, "not-admin", "another-password", role=cl.Role.ADMIN)
    with pytest.raises(cl.ManagedPermissionError):
        users.get_user(admin_principal, owner.user_id)
    with pytest.raises(cl.ManagedPermissionError):
        users.update_user(admin_principal, admin.user_id, role=cl.Role.USER)
    with pytest.raises(cl.ManagedPermissionError):
        users.update_user(member_principal, created.user_id, display_name="Nope")

    assert cl.require_admin(owner_principal) == owner_principal
    assert cl.require_admin(admin_principal) == admin_principal
    with pytest.raises(cl.AccessDenied):
        cl.require_admin(member_principal)
    with pytest.raises(cl.AccessDenied):
        cl.require_role(owner_principal, cl.Role.ADMIN)


def test_owner_protections_tombstones_and_safe_records():
    users, owner, admin, member = _service()
    owner_principal = users.authenticate("owner", "owner-password")

    assert owner_principal.as_dict() == {
        "user_id": owner.user_id,
        "display_name": "Owner",
        "role": "owner",
    }
    assert "auth_revision" not in owner_principal.as_dict()

    with pytest.raises(cl.ManagedValidationError):
        users.create_user(owner_principal, "other-owner", "other-owner-password", role=cl.Role.OWNER)
    with pytest.raises(cl.ManagedValidationError):
        users.create_user(owner_principal, "guest-user", "guest-user-password", role=cl.Role.GUEST)
    with pytest.raises(cl.ManagedPermissionError):
        users.update_user(owner_principal, owner.user_id, enabled=False)
    with pytest.raises(cl.ManagedPermissionError):
        users.update_user(owner_principal, owner.user_id, role=cl.Role.ADMIN)
    with pytest.raises(cl.ManagedPermissionError):
        users.delete_user(owner_principal, owner.user_id)

    users.update_user(owner_principal, admin.user_id, enabled=False)
    with pytest.raises(cl.ManagedPermissionError):
        users.transfer_owner(owner_principal, admin.user_id, "owner-password", "admin")

    tombstone = users.delete_user(owner_principal, member.user_id)
    assert tombstone.deleted and not tombstone.enabled
    assert {field.name for field in fields(tombstone)} == {
        "user_id", "username", "display_name", "role", "enabled", "deleted", "created_at", "updated_at"
    }
    assert "member-password" not in repr(tombstone)
    assert "password" not in repr(tombstone).lower()
    assert users.authenticate("member", "member-password") is None
    with pytest.raises(cl.ManagedConflictError):
        users.create_user(owner_principal, "MEMBER", "new-member-password")
    with pytest.raises(cl.ManagedNotFoundError):
        users.get_user(owner_principal, member.user_id)

    users.close()


def test_private_users_path_and_explicit_in_memory_keeper_close(tmp_path):
    home = tmp_path / "chatarch-home"
    users = cl.ManagedUsers.for_instance("private-users", home=home)
    expected = cl.state_paths("private-users", home=home).users_database
    assert users.store.database == expected
    assert expected.exists()
    assert not cl.state_paths("private-users", home=home).database.exists()
    users.close()

    memory = cl.ManagedUsers.in_memory("closed-users")
    memory.bootstrap_owner("owner", "owner-password")
    memory.close()
    with pytest.raises(ValueError):
        memory.authenticate("owner", "owner-password")
