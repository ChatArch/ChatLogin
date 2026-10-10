import pytest
import chatlogin as cl

@pytest.mark.parametrize("operation", ["list", "detail"])
def test_file_managed_reads_use_one_authorization_snapshot(tmp_path, monkeypatch, operation):
    users = cl.ManagedUsers.for_instance("race-read", home=tmp_path / "private-home")
    owner = users.bootstrap_owner("owner", "owner-password")
    operator = users.authenticate("owner", "owner-password")
    a = users.create_user(operator, "admin-a", "admin-a-password", role=cl.Role.ADMIN)
    b = users.create_user(operator, "admin-b", "admin-b-password", role=cl.Role.ADMIN)
    actor = users.authenticate("admin-a", "admin-a-password")
    original = users._actor
    def interleave(connection, candidate):
        row = original(connection, candidate)
        # Actual committed mutations between the two SELECTs, only if the first
        # SELECT is outside a transaction. No thread timing or fake store.
        if candidate.user_id == a.user_id and not connection.in_transaction:
            users.update_user(operator, a.user_id, role=cl.Role.USER)
            users.update_user(operator, b.user_id, role=cl.Role.USER)
        return row
    monkeypatch.setattr(users, "_actor", interleave)
    try:
        if operation == "list":
            assert b.user_id not in {r.user_id for r in users.list_users(actor)}
        else:
            with pytest.raises(cl.ManagedPermissionError):
                users.get_user(actor, b.user_id)
    finally:
        users.close()
