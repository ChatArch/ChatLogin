"""Concurrency contracts for bootstrap, transfer, and stale actor authority."""
from concurrent.futures import ThreadPoolExecutor

import pytest

import chatlogin as cl


def test_concurrent_empty_bootstrap_has_exactly_one_owner(tmp_path):
    users = cl.ManagedUsers.for_instance("bootstrap-race", home=tmp_path / "home")

    def bootstrap(index):
        try:
            return users.bootstrap_owner(f"owner{index}", "owner-password")
        except cl.ManagedConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(bootstrap, range(2)))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    owner = users.authenticate(winners[0].username, "owner-password")
    assert owner is not None and owner.role is cl.Role.OWNER
    assert len(users.list_users(owner)) == 1
    users.close()


def test_concurrent_transfer_keeps_one_owner_and_stale_admin_loses_authority():
    users = cl.ManagedUsers.in_memory("transfer-race", max_users=20)
    owner = users.bootstrap_owner("owner", "owner-password")
    owner_principal = users.authenticate("owner", "owner-password")
    admin = users.create_user(owner_principal, "admin", "admin-password", role=cl.Role.ADMIN)
    first = users.create_user(owner_principal, "first", "first-password")
    second = users.create_user(owner_principal, "second", "second-password")
    admin_principal = users.authenticate("admin", "admin-password")

    def transfer(target):
        try:
            return users.transfer_owner(owner_principal, target.user_id, "owner-password", target.username)
        except cl.ManagedPermissionError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(transfer, (first, second)))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    current_owner = users.authenticate(winners[0].username, "first-password" if winners[0].username == "first" else "second-password")
    assert current_owner.role is cl.Role.OWNER
    old_owner = users.authenticate("owner", "owner-password")
    assert old_owner.role is cl.Role.ADMIN

    # The actor was authenticated as admin before the owner changes it to a user.
    refreshed_owner = users.authenticate(winners[0].username, "first-password" if winners[0].username == "first" else "second-password")
    users.update_user(refreshed_owner, admin.user_id, role=cl.Role.USER)
    with pytest.raises(cl.ManagedPermissionError):
        users.create_user(admin_principal, "forbidden", "forbidden-password")
    users.close()
