import os
import pytest
from chatlogin import PrivateSQLite
import chatlogin.private_sqlite as module


@pytest.mark.skipif(os.name != "posix", reason="POSIX sidecar fault boundary")
def test_trusted_sqlite_journal_unlinked_after_open_is_absence_not_unsafe_link(tmp_path, monkeypatch):
    private = PrivateSQLite(tmp_path / "private" / "accounts.sqlite3")
    sidecar = private.path.parent / (private.path.name + "-journal") if hasattr(private, "path") else tmp_path / "private/accounts.sqlite3-journal"
    descriptor = os.open(sidecar, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    original = module.os.open
    removed = []
    def opened_then_committed(path, flags, *args, **kwargs):
        fd = original(path, flags, *args, **kwargs)
        if path == "accounts.sqlite3-journal" and not removed:
            # A concurrent SQLite commit removes the rollback journal while
            # inspection holds its already-open fd. No hardlink/symlink bypass.
            os.unlink(path, dir_fd=kwargs["dir_fd"])
            removed.append(True)
        return fd
    monkeypatch.setattr(module.os, "open", opened_then_committed)
    with private.connect() as connection:
        assert connection.execute("SELECT 1").fetchone() == (1,)
    assert removed and not sidecar.exists()
