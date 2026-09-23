"""Linux filesystem contracts for private SQLite databases."""
import importlib
import os
from pathlib import Path
import sqlite3
import stat
import sys
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

import chatlogin as cl


pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"),
                                reason="Linux no-follow filesystem contract")


def _assert_private_file(path: Path) -> None:
    details = path.stat(follow_symlinks=False)
    assert stat.S_ISREG(details.st_mode)
    assert details.st_uid == os.geteuid()
    assert details.st_nlink == 1
    assert stat.S_IMODE(details.st_mode) == 0o600


def test_private_sqlite_creates_private_topology_and_main_database_once(tmp_path):
    database = tmp_path / "private" / "sessions.sqlite3"
    previous_umask = os.umask(0o022)
    try:
        first = cl.PrivateSQLite(database)
        first_identity = (database.stat().st_dev, database.stat().st_ino)
        second = cl.PrivateSQLite(database)
    finally:
        os.umask(previous_umask)

    assert first.database == database
    assert second.database == database
    assert stat.S_IMODE(database.parent.stat().st_mode) == 0o700
    assert (database.stat().st_dev, database.stat().st_ino) == first_identity
    _assert_private_file(database)


def test_private_sqlite_connects_to_actual_path_in_rw_mode(tmp_path, monkeypatch):
    database = tmp_path / "private" / "name with # and ?.sqlite3"
    private = cl.PrivateSQLite(database)
    real_connect = sqlite3.connect
    calls = []

    def recording_connect(target, *args, **kwargs):
        calls.append((os.fspath(target), kwargs.copy()))
        return real_connect(target, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", recording_connect)
    with private.connect() as connection:
        connection.execute("CREATE TABLE example (value TEXT)")

    assert len(calls) == 1
    target, kwargs = calls[0]
    parsed = urlsplit(target)
    assert parsed.scheme == "file"
    assert Path(unquote(parsed.path)) == database.absolute()
    assert parse_qs(parsed.query)["mode"] == ["rw"]
    assert kwargs["uri"] is True
    assert "/proc/self/fd/" not in target
    assert "/dev/fd/" not in target


def test_real_wal_and_shm_are_created_and_accepted_in_trusted_directory(tmp_path):
    database = tmp_path / "private" / "sessions.sqlite3"
    previous_umask = os.umask(0o022)
    try:
        private = cl.PrivateSQLite(database)
        with private.connect() as connection:
            assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
            connection.execute("CREATE TABLE example (value TEXT)")
            connection.execute("INSERT INTO example VALUES ('one')")
            connection.commit()

            sidecars = [Path(f"{database}-wal"), Path(f"{database}-shm")]
            assert all(path.parent == database.parent and path.exists() for path in sidecars)
            for path in sidecars:
                _assert_private_file(path)

            reopened = cl.PrivateSQLite(database)
            with reopened.connect() as other:
                assert other.execute("SELECT value FROM example").fetchone() == ("one",)
    finally:
        os.umask(previous_umask)


def test_real_persist_journal_is_created_and_accepted_in_trusted_directory(tmp_path):
    database = tmp_path / "private" / "sessions.sqlite3"
    journal = Path(f"{database}-journal")
    previous_umask = os.umask(0o022)
    try:
        private = cl.PrivateSQLite(database)
        with private.connect() as connection:
            assert connection.execute("PRAGMA journal_mode=PERSIST").fetchone() == ("persist",)
            connection.execute("CREATE TABLE example (value TEXT)")
            connection.execute("INSERT INTO example VALUES ('one')")
            connection.commit()
            assert journal.exists() and journal.parent == database.parent
            _assert_private_file(journal)
    finally:
        os.umask(previous_umask)

    _assert_private_file(journal)
    reopened = cl.PrivateSQLite(database)
    with reopened.connect() as connection:
        assert connection.execute("SELECT value FROM example").fetchone() == ("one",)


def test_fresh_safe_sidecar_may_be_normalized_but_existing_one_is_not(tmp_path, monkeypatch):
    database = tmp_path / "private" / "sessions.sqlite3"
    sidecar = Path(f"{database}-wal")
    private = cl.PrivateSQLite(database)
    real_connect = sqlite3.connect

    def connect_then_create_sidecar(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        sidecar.write_bytes(b"")
        sidecar.chmod(0o644)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect_then_create_sidecar)
    with private.connect():
        pass
    _assert_private_file(sidecar)

    sidecar.chmod(0o640)
    with pytest.raises(ValueError):
        cl.PrivateSQLite(database)
    assert stat.S_IMODE(sidecar.stat().st_mode) == 0o640


def test_sqlite_refuses_existing_permissive_data_directory_before_creation(tmp_path):
    directory = tmp_path / "existing"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    database = directory / "sessions.sqlite3"

    with pytest.raises(ValueError):
        cl.PrivateSQLite(database)

    assert not database.exists()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o755


@pytest.mark.parametrize("mode", [0o644, 0o620, 0o604, 0o602, 0o660])
def test_sqlite_refuses_existing_permissive_database_without_mutation(tmp_path, mode):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    database = directory / "sessions.sqlite3"
    database.write_bytes(b"not a database")
    database.chmod(mode)

    with pytest.raises(ValueError):
        cl.PrivateSQLite(database)

    assert database.read_bytes() == b"not a database"
    assert stat.S_IMODE(database.stat().st_mode) == mode


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_sqlite_refuses_existing_permissive_sidecar_before_use(tmp_path, suffix):
    database = tmp_path / "private" / "sessions.sqlite3"
    cl.PrivateSQLite(database)
    sidecar = Path(f"{database}{suffix}")
    sidecar.write_bytes(b"historical")
    sidecar.chmod(0o640)

    with pytest.raises(ValueError):
        cl.PrivateSQLite(database)

    assert sidecar.read_bytes() == b"historical"
    assert stat.S_IMODE(sidecar.stat().st_mode) == 0o640


def test_sqlite_refuses_symlink_ancestor(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError):
        cl.PrivateSQLite(linked / "sessions.sqlite3")

    assert list(outside.iterdir()) == []


def test_sqlite_refuses_database_symlink_after_initialization(tmp_path):
    database = tmp_path / "private" / "sessions.sqlite3"
    outside = tmp_path / "outside.sqlite3"
    private = cl.PrivateSQLite(database)
    outside.write_bytes(b"sentinel")
    outside.chmod(0o600)
    database.unlink()
    database.symlink_to(outside)

    with pytest.raises(ValueError):
        with private.connect():
            pass

    assert outside.read_bytes() == b"sentinel"


def test_sqlite_does_not_recreate_database_removed_after_initialization(tmp_path):
    database = tmp_path / "private" / "sessions.sqlite3"
    private = cl.PrivateSQLite(database)
    database.unlink()

    with pytest.raises(ValueError):
        with private.connect():
            pass

    assert not database.exists()


@pytest.mark.parametrize("suffix,kind", [
    ("-wal", "symlink"),
    ("-shm", "hardlink"),
    ("-journal", "directory"),
])
def test_sqlite_refuses_other_unsafe_existing_sidecar_states(tmp_path, suffix, kind):
    database = tmp_path / "private" / "sessions.sqlite3"
    cl.PrivateSQLite(database)
    sidecar = Path(f"{database}{suffix}")
    outside = tmp_path / "outside"
    if kind == "symlink":
        outside.write_bytes(b"sentinel")
        sidecar.symlink_to(outside)
    elif kind == "hardlink":
        outside.write_bytes(b"sentinel")
        outside.chmod(0o600)
        os.link(outside, sidecar)
    else:
        sidecar.mkdir()

    with pytest.raises(ValueError):
        cl.PrivateSQLite(database)

    if outside.exists():
        assert outside.read_bytes() == b"sentinel"


def test_sqlite_refuses_hardlinked_database_without_mutation(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    outside = directory / "outside.sqlite3"
    outside.write_bytes(b"sentinel")
    outside.chmod(0o600)
    database = directory / "sessions.sqlite3"
    os.link(outside, database)

    with pytest.raises(ValueError):
        cl.PrivateSQLite(database)

    assert outside.read_bytes() == b"sentinel"


def test_sqlite_refuses_untrusted_writable_ancestor_without_creation(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o770)
    shared.chmod(0o770)
    database = shared / "private" / "sessions.sqlite3"

    with pytest.raises(ValueError):
        cl.PrivateSQLite(database)

    assert not database.parent.exists()


def test_sqlite_accepts_owned_sticky_writable_ancestor(tmp_path):
    sticky = tmp_path / "sticky"
    sticky.mkdir(mode=0o700)
    sticky.chmod(0o1777)
    database = sticky / "private" / "sessions.sqlite3"

    cl.PrivateSQLite(database)

    assert stat.S_IMODE(database.parent.stat().st_mode) == 0o700
    _assert_private_file(database)


def test_sqlite_refuses_ancestor_not_owned_by_root_or_service_uid(tmp_path, monkeypatch):
    private_module = importlib.import_module("chatlogin.private_sqlite")
    actual_uid = os.geteuid()
    service_uid = actual_uid + 1 if actual_uid != 0 else 1
    database = tmp_path / "private" / "sessions.sqlite3"
    monkeypatch.setattr(private_module.os, "geteuid", lambda: service_uid)

    with pytest.raises(ValueError):
        cl.PrivateSQLite(database)

    assert not database.exists()


def test_sqlite_session_store_put_get_delete_uses_private_sqlite(tmp_path):
    database = tmp_path / "private" / "sessions.sqlite3"
    store = cl.SQLiteSessionStore(database)
    session = cl.Session(cl.Principal("user"), 1000, "x" * 43)

    store.put("site", "1" * 64, session)
    assert store.get("site", "1" * 64) == session
    store.delete("site", "1" * 64)
    assert store.get("site", "1" * 64) is None
