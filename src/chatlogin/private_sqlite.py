"""Reusable SQLite connections rooted in a trusted private directory."""
from contextlib import contextmanager
from pathlib import Path
import errno
import os
import sqlite3
import stat


_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_O_PATH = getattr(os, "O_PATH", getattr(os, "O_SEARCH", os.O_RDONLY))
_SIDECAR_SUFFIXES = ("-journal", "-wal", "-shm")


def _identity(details) -> tuple[int, int]:
    return details.st_dev, details.st_ino


def _legacy_private_parents(directory: Path) -> None:
    """Preserve the pre-0.1.4 directory behavior on non-POSIX systems."""
    if directory.exists():
        return
    _legacy_private_parents(directory.parent)
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        pass


def _validate_directory(details, *, final: bool, service_uid: int,
                        root_uid: int) -> None:
    if not stat.S_ISDIR(details.st_mode):
        raise ValueError("Private SQLite path components must be real directories")
    if details.st_uid not in (0, root_uid, service_uid):
        raise ValueError("Private SQLite ancestors must be owned by root or the service user")

    mode = stat.S_IMODE(details.st_mode)
    if final:
        if details.st_uid != service_uid or mode != 0o700:
            raise ValueError("Private SQLite data directory must be service-user-owned mode 0700")
        return

    untrusted_write = mode & (stat.S_IWGRP | stat.S_IWOTH)
    # A trusted owner plus sticky semantics prevents an untrusted writer from
    # replacing that owner's child; the child owner/type is validated next.
    sticky_owner_protection = bool(mode & stat.S_ISVTX)
    if untrusted_write and not sticky_owner_protection:
        raise ValueError("Private SQLite ancestors must not be writable by group or other users")


def _validate_file_shape(details, label: str) -> None:
    if not stat.S_ISREG(details.st_mode):
        raise ValueError(f"{label} must be a regular, non-symlink file")
    if details.st_nlink != 1:
        raise ValueError(f"{label} must have exactly one link")


def _validate_private_file(details, label: str, service_uid: int) -> None:
    _validate_file_shape(details, label)
    if details.st_uid != service_uid:
        raise ValueError(f"{label} must be owned by the service user")
    if stat.S_IMODE(details.st_mode) != 0o600:
        raise ValueError(f"{label} must have mode 0600")


class _LegacyPrivateSQLite:
    """Compatibility path without POSIX no-follow or mode guarantees."""

    def __init__(self, database: Path, timeout: float):
        self.database = database
        self.timeout = timeout
        _legacy_private_parents(database.parent)
        try:
            fd = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if database.is_symlink() or not database.is_file():
                raise ValueError("SQLite database must be a regular, non-symlink file")
        else:
            os.close(fd)

    @contextmanager
    def connect(self, *, immediate: bool = False):
        connection = sqlite3.connect(self.database, timeout=self.timeout)
        try:
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise
            else:
                connection.commit()
        finally:
            try:
                if connection.in_transaction:
                    connection.rollback()
            finally:
                connection.close()


class _POSIXPrivateSQLite:
    """POSIX implementation backed by a trusted directory topology."""

    def __init__(self, database: Path, timeout: float):
        supports_dir_fd = getattr(os, "supports_dir_fd", ())
        required_dir_fd = (os.open, os.mkdir, os.stat, os.chmod)
        supports_follow = getattr(os, "supports_follow_symlinks", ())
        if (not _O_DIRECTORY or not _O_NOFOLLOW
                or any(function not in supports_dir_fd for function in required_dir_fd)
                or os.stat not in supports_follow):
            raise ValueError("Secure POSIX directory traversal is unavailable")
        self.database = database
        self.timeout = timeout
        self.service_uid = os.geteuid()
        self.path = os.path.abspath(os.fspath(database))
        if "\x00" in self.path:
            raise ValueError("SQLite database path must not contain NUL")
        self.name = os.path.basename(self.path)
        if not self.name:
            raise ValueError("SQLite database path must name a file")
        self.parent = os.path.dirname(self.path)
        self.root_uid = None
        self._directory_identities = None
        self._database_identity = None

        parent_fd, identities = self._open_directory(create=True)
        try:
            database_fd, database_identity = self._open_database(parent_fd, create=True)
            os.close(database_fd)
            self._inspect_sidecars(parent_fd)
        finally:
            os.close(parent_fd)
        self._directory_identities = identities
        self._database_identity = database_identity
        self.uri = f"{Path(self.path).as_uri()}?mode=rw&nofollow=1"

    def _open_directory(self, *, create: bool, expected=None):
        components = [component for component in self.parent.split(os.sep) if component]
        flags = _O_PATH | _O_CLOEXEC | _O_DIRECTORY | _O_NOFOLLOW
        try:
            current_fd = os.open(os.sep, flags)
        except OSError as exc:
            raise ValueError("Cannot securely open the private SQLite root") from exc

        identities = []
        try:
            root_details = os.fstat(current_fd)
            if self.root_uid is None:
                self.root_uid = root_details.st_uid
            elif root_details.st_uid != self.root_uid:
                raise ValueError("Private SQLite root identity changed")
            _validate_directory(root_details, final=not components,
                                service_uid=self.service_uid, root_uid=self.root_uid)
            identities.append(_identity(root_details))
            for index, component in enumerate(components):
                created = False
                try:
                    child_fd = os.open(component, flags, dir_fd=current_fd)
                except OSError as exc:
                    if not create or exc.errno != errno.ENOENT:
                        raise ValueError("Private SQLite path contains an unsafe ancestor") from exc
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=current_fd)
                        created = True
                    except FileExistsError:
                        pass
                    except OSError as mkdir_exc:
                        raise ValueError("Cannot securely create a private SQLite directory") from mkdir_exc
                    if created:
                        try:
                            os.chmod(component, 0o700, dir_fd=current_fd)
                        except OSError as chmod_exc:
                            raise ValueError("Cannot set a new private SQLite directory to mode 0700") from chmod_exc
                    try:
                        child_fd = os.open(component, flags, dir_fd=current_fd)
                    except OSError as open_exc:
                        raise ValueError("Private SQLite path contains an unsafe ancestor") from open_exc

                try:
                    child_details = os.fstat(child_fd)
                    try:
                        current_details = os.stat(component, dir_fd=current_fd,
                                                  follow_symlinks=False)
                    except OSError as exc:
                        raise ValueError("Private SQLite ancestor identity changed") from exc
                    final = index == len(components) - 1
                    _validate_directory(child_details, final=final,
                                        service_uid=self.service_uid,
                                        root_uid=self.root_uid)
                    if _identity(child_details) != _identity(current_details):
                        raise ValueError("Private SQLite ancestor identity changed")
                    if created and (child_details.st_uid != self.service_uid
                                    or stat.S_IMODE(child_details.st_mode) != 0o700):
                        raise ValueError("New private SQLite directories must be owned mode 0700")
                except BaseException:
                    os.close(child_fd)
                    raise

                os.close(current_fd)
                current_fd = child_fd
                identities.append(_identity(child_details))

            identities = tuple(identities)
            if expected is not None and identities != expected:
                raise ValueError("Private SQLite ancestor identity changed")
            return current_fd, identities
        except BaseException:
            os.close(current_fd)
            raise

    def _open_database(self, parent_fd: int, *, create: bool):
        flags = os.O_RDONLY | _O_CLOEXEC | _O_NOFOLLOW | _O_NONBLOCK
        try:
            before = os.stat(self.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            if not create:
                raise ValueError("Private SQLite database was removed")
            try:
                database_fd = os.open(
                    self.name,
                    os.O_RDWR | _O_CLOEXEC | _O_NOFOLLOW | _O_NONBLOCK
                    | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=parent_fd,
                )
            except OSError as exc:
                raise ValueError("Cannot securely create the private SQLite database") from exc
            try:
                os.fchmod(database_fd, 0o600)
            except OSError as exc:
                os.close(database_fd)
                raise ValueError("Cannot set the new SQLite database to mode 0600") from exc
        except OSError as exc:
            raise ValueError("Cannot securely inspect the private SQLite database") from exc
        else:
            _validate_private_file(before, "SQLite database", self.service_uid)
            try:
                database_fd = os.open(self.name, flags, dir_fd=parent_fd)
            except OSError as exc:
                raise ValueError("Cannot securely open the private SQLite database") from exc

        try:
            opened = os.fstat(database_fd)
            try:
                current = os.stat(self.name, dir_fd=parent_fd, follow_symlinks=False)
            except OSError as exc:
                raise ValueError("Private SQLite database identity changed") from exc
            _validate_private_file(opened, "SQLite database", self.service_uid)
            _validate_private_file(current, "SQLite database", self.service_uid)
            identity = _identity(opened)
            if identity != _identity(current):
                raise ValueError("Private SQLite database identity changed")
            if self._database_identity is not None and identity != self._database_identity:
                raise ValueError("Private SQLite database identity changed")
            return database_fd, identity
        except BaseException:
            os.close(database_fd)
            raise

    def _inspect_sidecar(self, parent_fd: int, suffix: str, *, normalize: bool):
        sidecar_name = self.name + suffix
        label = f"SQLite {suffix} sidecar"
        flags = os.O_RDONLY | _O_CLOEXEC | _O_NOFOLLOW | _O_NONBLOCK

        for _ in range(3):
            try:
                before = os.stat(sidecar_name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return None
            except OSError as exc:
                raise ValueError(f"Cannot securely inspect {label}") from exc

            _validate_file_shape(before, label)
            if before.st_uid != self.service_uid:
                raise ValueError(f"{label} must be owned by the service user")
            if not normalize and stat.S_IMODE(before.st_mode) != 0o600:
                raise ValueError(f"{label} must have mode 0600")
            try:
                sidecar_fd = os.open(sidecar_name, flags, dir_fd=parent_fd)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise ValueError(f"Cannot securely open {label}") from exc

            try:
                opened = os.fstat(sidecar_fd)
                _validate_file_shape(opened, label)
                if opened.st_uid != self.service_uid:
                    raise ValueError(f"{label} must be owned by the service user")
                if _identity(opened) != _identity(before):
                    continue
                if normalize and stat.S_IMODE(opened.st_mode) != 0o600:
                    try:
                        os.fchmod(sidecar_fd, 0o600)
                    except OSError as exc:
                        raise ValueError(f"Cannot set fresh {label} to mode 0600") from exc
                    opened = os.fstat(sidecar_fd)
                _validate_private_file(opened, label, self.service_uid)
                try:
                    current = os.stat(sidecar_name, dir_fd=parent_fd,
                                      follow_symlinks=False)
                except FileNotFoundError:
                    return None
                except OSError as exc:
                    raise ValueError(f"Cannot securely recheck {label}") from exc
                if _identity(opened) != _identity(current):
                    continue
                _validate_private_file(current, label, self.service_uid)
                return _identity(current)
            finally:
                os.close(sidecar_fd)

        raise ValueError(f"{label} identity changed repeatedly")

    def _inspect_sidecars(self, parent_fd: int, *, preexisting=None):
        identities = {}
        for suffix in _SIDECAR_SUFFIXES:
            if preexisting is None:
                identity = self._inspect_sidecar(parent_fd, suffix, normalize=False)
            else:
                try:
                    current = os.stat(self.name + suffix, dir_fd=parent_fd,
                                      follow_symlinks=False)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise ValueError(f"Cannot securely inspect SQLite {suffix} sidecar") from exc
                normalize = preexisting.get(suffix) != _identity(current)
                identity = self._inspect_sidecar(parent_fd, suffix, normalize=normalize)
            if identity is not None:
                identities[suffix] = identity
        return identities

    def _verify_state(self, parent_fd: int, preexisting) -> None:
        held_parent = os.fstat(parent_fd)
        _validate_directory(held_parent, final=True, service_uid=self.service_uid,
                            root_uid=self.root_uid)
        if _identity(held_parent) != self._directory_identities[-1]:
            raise ValueError("Private SQLite data directory identity changed")

        check_fd, identities = self._open_directory(
            create=False, expected=self._directory_identities,
        )
        os.close(check_fd)
        if identities != self._directory_identities:
            raise ValueError("Private SQLite ancestor identity changed")

        database_fd, identity = self._open_database(parent_fd, create=False)
        os.close(database_fd)
        if identity != self._database_identity:
            raise ValueError("Private SQLite database identity changed")
        self._inspect_sidecars(parent_fd, preexisting=preexisting)

    @contextmanager
    def connect(self, *, immediate: bool = False):
        parent_fd, identities = self._open_directory(
            create=False, expected=self._directory_identities,
        )
        connection = None
        preexisting = {}
        try:
            if identities != self._directory_identities:
                raise ValueError("Private SQLite ancestor identity changed")
            database_fd, identity = self._open_database(parent_fd, create=False)
            os.close(database_fd)
            if identity != self._database_identity:
                raise ValueError("Private SQLite database identity changed")
            preexisting = self._inspect_sidecars(parent_fd)

            connection = sqlite3.connect(self.uri, uri=True, timeout=self.timeout)
            self._verify_state(parent_fd, preexisting)
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_state(parent_fd, preexisting)
            try:
                yield connection
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                self._verify_state(parent_fd, preexisting)
                raise
            else:
                self._verify_state(parent_fd, preexisting)
                connection.commit()
                self._verify_state(parent_fd, preexisting)
        finally:
            try:
                if connection is not None:
                    try:
                        if connection.in_transaction:
                            connection.rollback()
                    finally:
                        connection.close()
            finally:
                try:
                    if connection is not None:
                        self._verify_state(parent_fd, preexisting)
                finally:
                    os.close(parent_fd)


class PrivateSQLite:
    """Own a SQLite file inside a validated private local directory.

    On POSIX, existing paths are never chmodded. Newly created directories and
    the main database are initialized to 0700/0600, while safe sidecars first
    observed during a connection may be normalized to 0600. Non-POSIX systems
    use the package's isolated legacy compatibility behavior and make no
    POSIX no-follow or mode guarantee.
    """

    def __init__(self, database: str | Path, *, timeout: float = 5):
        self.database = Path(database)
        self.timeout = timeout
        if os.name == "posix":
            self._implementation = _POSIXPrivateSQLite(self.database, timeout)
        else:
            self._implementation = _LegacyPrivateSQLite(self.database, timeout)

    @contextmanager
    def connect(self, *, immediate: bool = False):
        """Yield one real-path connection and commit or roll back on exit."""
        with self._implementation.connect(immediate=immediate) as connection:
            yield connection
