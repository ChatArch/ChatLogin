"""Platform guard for private SQLite files; POSIX bits are not Windows ACLs."""
import os
from types import SimpleNamespace

import chatlogin.sqlite as store_module
from chatlogin import SQLiteSessionStore


def test_existing_database_does_not_treat_non_posix_mode_bits_as_acls(tmp_path, monkeypatch):
    database = tmp_path / "sessions.sqlite3"
    SQLiteSessionStore(database)
    database.chmod(0o644)
    original = store_module.os
    shim = SimpleNamespace(name="nt", open=original.open, close=original.close,
                           O_CREAT=original.O_CREAT, O_EXCL=original.O_EXCL,
                           O_WRONLY=original.O_WRONLY)
    monkeypatch.setattr(store_module, "os", shim)
    SQLiteSessionStore(database)
    assert database.is_file()
