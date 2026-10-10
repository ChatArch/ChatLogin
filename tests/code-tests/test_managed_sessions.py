"""Managed sessions share account revisions and invalidate across namespaces."""
import pytest

import chatlogin as cl


def _shared_services():
    store = cl.SQLiteUserStore.in_memory("managed-account", max_users=20, max_sessions=20)
    primary = cl.ManagedUsers(store, session_namespace="site-one", ttl=3600)
    secondary = cl.ManagedUsers(store, session_namespace="site-two", ttl=3600)
    owner = primary.bootstrap_owner("owner", "owner-password")
    member = primary.create_user(
        primary.authenticate("owner", "owner-password"), "member", "member-password"
    )
    return primary, secondary, owner, member


def test_managed_sessions_are_namespace_scoped_and_all_invalidated():
    primary, secondary, owner, member = _shared_services()
    owner_principal = primary.authenticate("owner", "owner-password")
    member_principal = primary.authenticate("member", "member-password")
    first = primary.sessions.issue(member_principal)
    second = secondary.sessions.issue(member_principal)
    assert primary.sessions.resolve(first.token).principal.user_id == member.user_id
    assert secondary.sessions.resolve(first.token) is None
    assert secondary.sessions.resolve(second.token).principal.user_id == member.user_id

    primary.update_user(owner_principal, member.user_id, enabled=False)
    assert primary.sessions.resolve(first.token) is None
    assert secondary.sessions.resolve(second.token) is None
    assert primary.authenticate("member", "member-password") is None

    primary.update_user(owner_principal, member.user_id, enabled=True)
    member_principal = primary.authenticate("member", "member-password")
    first = primary.sessions.issue(member_principal)
    second = secondary.sessions.issue(member_principal)
    primary.update_user(owner_principal, member.user_id, role=cl.Role.ADMIN)
    assert primary.sessions.resolve(first.token) is None
    assert secondary.sessions.resolve(second.token) is None

    member_principal = primary.authenticate("member", "member-password")
    first = primary.sessions.issue(member_principal)
    second = secondary.sessions.issue(member_principal)
    primary.reset_password(owner_principal, member.user_id, "changed-member-password")
    assert primary.sessions.resolve(first.token) is None
    assert secondary.sessions.resolve(second.token) is None
    assert primary.authenticate("member", "member-password") is None
    current = primary.authenticate("member", "changed-member-password")
    assert current is not None
    issued = primary.sessions.issue(current)
    primary.change_password(current, "changed-member-password", "final-member-password")
    assert primary.sessions.resolve(issued.token) is None
    assert primary.authenticate("member", "changed-member-password") is None
    assert primary.authenticate("member", "final-member-password") is not None
    primary.close()


def test_verified_old_password_cannot_issue_after_reset():
    primary, _, owner, member = _shared_services()
    owner_principal = primary.authenticate("owner", "owner-password")
    verified_before_reset = primary.authenticate("member", "member-password")
    assert verified_before_reset.auth_revision == 0

    primary.reset_password(owner_principal, member.user_id, "changed-member-password")
    with pytest.raises(cl.ManagedPermissionError):
        primary.sessions.issue(verified_before_reset)
    assert primary.authenticate("member", "member-password") is None
    current = primary.authenticate("member", "changed-member-password")
    assert primary.sessions.resolve(primary.sessions.issue(current).token).principal.user_id == member.user_id
    primary.close()
