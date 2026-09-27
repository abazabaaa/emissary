"""Real filesystems: write an inventory to disk and walk a directory back.

:func:`materialize` lays an :class:`~campaign_detector.inventory.Inventory`
down under a destination directory (sparse files by default, so terabytes of
trajectory chunks cost no disk) and records what an unprivileged process
cannot set -- owner uid/gid, ctime -- plus each file's recorded sha256 in a
:class:`Manifest`, also written as ``<dest>.owners.tsv``.

:func:`walk_fs` is the crawler: a dirfd-relative ``os.scandir`` walk that
never follows symlinks (unless asked), decodes names with ``surrogateescape``
and emits ``/`` and every ancestor of the walked root, so its output is a
strict inventory the detector reads directly. ``map_root`` rewrites the
on-disk prefix (``/tmp/kdr_fs`` -> ``/``) and ``owners`` overlays a sidecar.
"""

from __future__ import annotations

import errno
import hashlib
import os
import random
import stat
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Union

from .inventory import Entry, Inventory, normalize_path

__all__ = [
    "MAX_DENSE_SIZE", "OWNERS_SUFFIX", "OWNERS_COLUMNS", "Manifest", "materialize", "load_owners", "walk_fs",
]

MAX_DENSE_SIZE = 64 * 1024 * 1024
"""Largest file ``materialize(..., sparse=False)`` will fill with real bytes."""

OWNERS_SUFFIX = ".owners.tsv"
"""Sidecar written next to ``dest``: ``<dest>.owners.tsv``."""

OWNERS_COLUMNS: tuple[str, ...] = ("path", "uid", "gid", "sha256", "ctime")
"""Sidecar TSV columns; ``sha256`` is empty for directories, symlinks and unhashed files."""

_CHUNK = 1024 * 1024
_TSV_BREAKERS = ("\t", "\n", "\r")  # Inventory.from_tsv reads with newline="", so \r ends a row too
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


@dataclass
class Manifest:
    """What :func:`materialize` could not write into the filesystem itself.

    Keys are inventory paths (``/vol3/...``). ``root_map`` is the
    ``map_root`` that turns on-disk paths back into inventory paths;
    ``sidecar`` is where the TSV copy lives.
    """

    dest: str
    root_map: tuple[str, str]
    owners: dict[str, tuple[int, int]] = field(default_factory=dict)
    sha: dict[str, str] = field(default_factory=dict)
    ctime: dict[str, int] = field(default_factory=dict)
    sidecar: str = ""

    def to_tsv(self, dst: str | os.PathLike[str]) -> None:
        """Write the sidecar TSV (header row, then one row per path, sorted)."""
        with open(dst, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.write("\t".join(OWNERS_COLUMNS) + "\n")
            for p in sorted(self.owners):
                uid, gid = self.owners[p]
                ctime = self.ctime.get(p)
                cells = [p, str(uid), str(gid), self.sha.get(p, ""), "" if ctime is None else str(ctime)]
                if any(ch in c for c in cells for ch in _TSV_BREAKERS):
                    raise ValueError(f"tab, newline or carriage return in sidecar row for {p!r}")
                fh.write("\t".join(cells) + "\n")


def load_owners(src: str | os.PathLike[str]) -> Manifest:
    """Read a sidecar written by :meth:`Manifest.to_tsv`.

    ``dest`` and ``root_map`` are inferred from a ``<dest>.owners.tsv`` name
    (empty ``dest`` otherwise). The ``ctime`` column is optional.
    """
    src = os.fspath(src)
    dest = src[: -len(OWNERS_SUFFIX)] if src.endswith(OWNERS_SUFFIX) else ""
    man = Manifest(dest=dest, root_map=(dest, "/"), sidecar=src)
    with open(src, encoding="utf-8", errors="surrogateescape", newline="") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        if header[:4] != list(OWNERS_COLUMNS[:4]):
            raise ValueError(f"unexpected owners header: {header!r}")
        for lineno, line in enumerate(fh, start=2):
            line = line.rstrip("\n")
            if not line:
                continue
            cells = line.split("\t")
            if len(cells) != len(header):
                raise ValueError(f"{src}:{lineno}: expected {len(header)} columns, got {len(cells)}")
            row = dict(zip(header, cells))
            p = row["path"]
            man.owners[p] = (int(row["uid"]), int(row["gid"]))
            if row["sha256"]:
                man.sha[p] = row["sha256"]
            if row.get("ctime"):
                man.ctime[p] = int(row["ctime"])
    return man


# --------------------------------------------------------------------------
# materialize
# --------------------------------------------------------------------------


def _dense_bytes(seed: str, size: int) -> Iterator[bytes]:
    """Deterministic pseudo-random content of ``size`` bytes, in 1 MiB blocks."""
    rng = random.Random(seed.encode("utf-8", "surrogateescape"))
    left = size
    while left > 0:
        n = min(left, _CHUNK)
        yield rng.randbytes(n)
        left -= n


def materialize(inv: Inventory, dest: str | os.PathLike[str], *, sparse: bool = True) -> Manifest:
    """Write ``inv`` under ``dest`` (``/vol3/x`` becomes ``<dest>/vol3/x``).

    ``dest`` must be missing or an empty directory; the inventory's ``/``
    maps to ``dest`` itself. Files get their recorded size: sparse
    (``truncate``) by default, or with ``sparse=False`` real bytes seeded by
    the entry's sha256 (so copies are byte-identical), which raises
    ``ValueError`` if any file exceeds :data:`MAX_DENSE_SIZE`. Symlink targets
    are written verbatim; files sharing an inode (``nlink > 1``) become hard
    links (keyed by inode, size, mtime and uid, as in ``detect``, because inode numbers
    repeat across volumes); mtimes (and atimes) are set deepest first so directory mtimes stick.
    uid/gid, ctime and the recorded sha256 go into the returned
    :class:`Manifest` and ``<dest>.owners.tsv``.
    """
    dest_s = os.path.abspath(os.fspath(dest))
    if not sparse:
        big = [e for e in inv.files() if e.size > MAX_DENSE_SIZE]
        if big:
            raise ValueError(f"sparse=False writes real bytes only for files up to {MAX_DENSE_SIZE} bytes; "
                             f"{len(big)} files are larger (first: {big[0].path}, {big[0].size} bytes)")
    for e in inv.links():
        if not e.target:
            raise ValueError(f"symlink without a target: {e.path!r}")
    if os.path.lexists(dest_s):
        if not os.path.isdir(dest_s) or os.path.islink(dest_s) or os.listdir(dest_s):
            raise FileExistsError(errno.EEXIST, "destination exists and is not an empty directory", dest_s)
    else:
        os.makedirs(dest_s)
    dest_b = os.fsencode(dest_s)

    def disk(p: str) -> bytes:
        return dest_b if p == "/" else dest_b + os.fsencode(p)

    first_link: dict[tuple[int, int, int, int], bytes] = {}
    for e in inv:  # sorted by path: parents before children
        if e.path == "/":
            continue
        d = disk(e.path)
        if e.kind == "d":
            os.mkdir(d)
        elif e.kind == "l":
            os.symlink(os.fsencode(str(e.target)), d)
        elif e.nlink > 1 and (e.inode, e.size, e.mtime, e.uid) in first_link:
            os.link(first_link[(e.inode, e.size, e.mtime, e.uid)], d)
        else:
            with open(d, "wb") as fh:
                if sparse:
                    fh.truncate(e.size)
                else:
                    for block in _dense_bytes(e.sha256 or e.path, e.size):
                        fh.write(block)
            if e.nlink > 1:
                first_link[(e.inode, e.size, e.mtime, e.uid)] = d
    for e in sorted(inv, key=lambda x: (-x.path.count("/") if x.path != "/" else 1, x.path)):
        ns = e.mtime * 1_000_000_000
        os.utime(disk(e.path), ns=(ns, ns), follow_symlinks=False)

    man = Manifest(dest=dest_s, root_map=(dest_s, "/"), sidecar=dest_s.rstrip("/") + OWNERS_SUFFIX)
    for e in inv:
        man.owners[e.path] = (e.uid, e.gid)
        man.ctime[e.path] = e.ctime
        if e.sha256:
            man.sha[e.path] = e.sha256
    man.to_tsv(man.sidecar)
    return man


# --------------------------------------------------------------------------
# walk
# --------------------------------------------------------------------------

OwnersArg = Union[str, os.PathLike, Manifest, Mapping[str, tuple], None]
"""Accepted ``owners`` values of :func:`walk_fs`."""


def _secs(ns: int) -> int:
    return ns // 1_000_000_000


def _owner_table(owners: OwnersArg) -> dict[str, tuple[int, int, str | None, int | None]]:
    """Normalise ``owners`` to ``path -> (uid, gid, sha256|None, ctime|None)``."""
    if owners is None:
        return {}
    if isinstance(owners, (str, os.PathLike)):
        owners = load_owners(owners)
    if isinstance(owners, Manifest):
        return {p: (uid, gid, owners.sha.get(p), owners.ctime.get(p)) for p, (uid, gid) in owners.owners.items()}
    out = {}
    for p, row in owners.items():
        uid, gid, *rest = row
        out[p] = (int(uid), int(gid), rest[0] if rest else None, int(rest[1]) if len(rest) > 1 else None)
    return out


class _Walk:
    def __init__(self, root: str, map_root: tuple[str, str] | None, do_hash: bool, owners: OwnersArg,
                 follow: bool, on_error: Callable[[OSError], None] | None) -> None:
        self.root = os.path.abspath(root)
        if map_root is not None:
            src, dst = os.path.abspath(map_root[0]), normalize_path(map_root[1])
            if not (self.root == src or self.root.startswith(src.rstrip("/") + "/")):
                raise ValueError(f"root {self.root!r} is not under map_root source {src!r}")
            self.map: tuple[str, str] | None = (src, dst)
        else:
            self.map = None
        self.do_hash = do_hash
        self.owners = _owner_table(owners)
        self.follow = follow
        self.on_error = on_error
        self.errors: list[str] = []
        self.entries: list[Entry] = []
        self.open_dirs: set[tuple[int, int]] = set()

    # -- helpers -----------------------------------------------------------

    def mapped(self, disk_path: str) -> str:
        if self.map is None:
            return normalize_path(disk_path)
        src, dst = self.map
        rest = disk_path[len(src):]
        return normalize_path(dst + "/" + rest) if rest else dst

    def unmapped(self, path: str) -> str | None:
        """On-disk path of inventory ``path``, or ``None`` above the mapped prefix."""
        if self.map is None:
            return path
        src, dst = self.map
        if dst == "/" or path == dst or path.startswith(dst + "/"):
            return src + path[len(dst.rstrip("/")):] if path != dst else src
        return None

    def error(self, exc: OSError, disk_path: str | None = None) -> None:
        if disk_path is not None:
            exc.filename = disk_path
        code = errno.errorcode.get(exc.errno or 0, "?")
        self.errors.append(f"{exc.filename}: {code} {exc.strerror or exc}")
        if self.on_error is not None:
            self.on_error(exc)

    def add(self, path: str, kind: str, size: int, mtime: int, ctime: int, uid: int, gid: int, inode: int,
            nlink: int, sha: str | None = None, target: str | None = None) -> None:
        """Append one entry, overlaying the owners table."""
        own = self.owners.get(path)
        if own is not None:
            uid, gid = own[0], own[1]
            if own[2] and not self.do_hash and kind == "f":
                sha = own[2]
            if own[3] is not None:
                ctime = own[3]
        self.entries.append(Entry(path, kind, size, mtime, ctime, uid, gid, inode, nlink, sha256=sha, target=target))

    def emit(self, path: str, st: os.stat_result, kind: str, *, sha: str | None = None,
             target: str | None = None) -> None:
        size = 0 if kind == "d" else len(target or "") if kind == "l" else st.st_size
        self.add(path, kind, size, _secs(st.st_mtime_ns), _secs(st.st_ctime_ns), st.st_uid, st.st_gid, st.st_ino,
                 st.st_nlink, sha, target)

    def hash_file(self, name: str, dir_fd: int, disk_path: str) -> str | None:
        flags = os.O_RDONLY | _O_CLOEXEC | _O_NONBLOCK | (0 if self.follow else _O_NOFOLLOW)
        try:
            fd = os.open(name, flags, dir_fd=dir_fd)
        except OSError as exc:
            self.error(exc, disk_path)
            return None
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return None
            h = hashlib.sha256()
            while True:
                block = os.read(fd, _CHUNK)
                if not block:
                    return h.hexdigest()
                h.update(block)
        except OSError as exc:
            self.error(exc, disk_path)
            return None
        finally:
            os.close(fd)

    # -- walk --------------------------------------------------------------

    def ancestors(self, root_path: str, root_st: os.stat_result) -> None:
        """Emit ``/`` and every ancestor of the mapped root as directories."""
        parts = [p for p in root_path.split("/") if p]
        for i in range(len(parts)):
            path = "/" + "/".join(parts[:i])
            disk = self.unmapped(path)
            st = None
            if disk is not None:
                try:
                    st = os.stat(disk)
                except OSError as exc:
                    self.error(exc)
            if st is None or not stat.S_ISDIR(st.st_mode):  # above the mapped prefix, or unreadable
                self.add(path, "d", 0, _secs(root_st.st_mtime_ns), _secs(root_st.st_ctime_ns), root_st.st_uid,
                         root_st.st_gid, 0, 2)
            else:
                self.emit(path, st, "d")

    def scan(self, fd: int, disk_dir: str, inv_dir: str) -> list[tuple[str, str, str]]:
        """Emit the entries of the open directory ``fd``; returns its subdirs to descend."""
        subdirs: list[tuple[str, str, str]] = []
        try:
            it = os.scandir(fd)
        except OSError as exc:
            self.error(exc, disk_dir)
            return subdirs
        with it:
            while True:
                try:
                    de = next(it)
                except StopIteration:
                    break
                except OSError as exc:  # ESTALE/EIO mid-listing: keep what was read
                    self.error(exc, disk_dir)
                    break
                name = de.name  # str, undecodable bytes as surrogates
                disk_path = os.path.join(disk_dir, name)
                path = inv_dir.rstrip("/") + "/" + name
                if any(ch in name for ch in _TSV_BREAKERS):
                    self.error(OSError(errno.EINVAL, "tab or line break in name (not representable in TSV)",
                                       disk_path))
                    continue
                try:
                    lst = de.stat(follow_symlinks=False)
                except OSError as exc:
                    self.error(exc, disk_path)
                    continue
                st = lst
                if self.follow and stat.S_ISLNK(lst.st_mode):
                    try:
                        st = os.stat(name, dir_fd=fd)
                    except OSError:
                        st = lst  # dangling or looping link: keep it as a link
                    if not stat.S_ISREG(st.st_mode):
                        st = lst  # only links to regular files are followed; linked dirs stay links
                mode = st.st_mode
                if stat.S_ISLNK(mode):
                    try:
                        target = os.readlink(name, dir_fd=fd)
                    except OSError as exc:
                        self.error(exc, disk_path)
                        continue
                    if any(ch in target for ch in _TSV_BREAKERS):
                        self.error(OSError(errno.EINVAL, "tab or line break in symlink target", disk_path))
                        continue
                    self.emit(path, st, "l", target=target)
                elif stat.S_ISDIR(mode):
                    self.emit(path, st, "d")
                    if (st.st_dev, st.st_ino) not in self.open_dirs:  # else a bind mount of an ancestor
                        subdirs.append((name, disk_path, path))
                elif stat.S_ISREG(mode):
                    sha = self.hash_file(name, fd, disk_path) if self.do_hash else None
                    self.emit(path, st, "f", sha=sha)
                # sockets, fifos and devices are not inventory kinds: skipped
        return subdirs

    def open_dir(self, name: str, dir_fd: int | None, disk_path: str, *, nofollow: bool = True) -> int | None:
        flags = os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC | (_O_NOFOLLOW if nofollow else 0)
        try:
            return os.open(name, flags, dir_fd=dir_fd)
        except OSError as exc:
            self.error(exc, disk_path)
            return None

    def run(self) -> Inventory:
        root_path = self.mapped(self.root)
        root_st = os.stat(self.root)  # the named root may itself be a symlink to a directory
        if not stat.S_ISDIR(root_st.st_mode):
            raise NotADirectoryError(errno.ENOTDIR, "walk root is not a directory", self.root)
        self.ancestors(root_path, root_st)
        self.emit(root_path, root_st, "d")
        fd = self.open_dir(self.root, None, self.root, nofollow=False)
        if fd is None:
            return self.result()
        # Depth-first with one open fd per level: each child is opened relative to its parent's fd.
        stack: list[tuple[int, tuple[int, int], list[tuple[str, str, str]]]] = []
        try:
            self.push(stack, fd, self.root, root_path)
            while stack:
                fd, key, todo = stack[-1]
                if not todo:
                    stack.pop()
                    self.open_dirs.discard(key)
                    os.close(fd)
                    continue
                name, disk_path, path = todo.pop()
                child = self.open_dir(name, fd, disk_path)
                if child is not None:
                    self.push(stack, child, disk_path, path)
        finally:  # on_error may raise to abort: release every directory still open
            for fd, _, _ in stack:
                os.close(fd)
        return self.result()

    def push(self, stack: list, fd: int, disk_path: str, path: str) -> None:
        """Put the open directory ``fd`` on ``stack`` (owning it from here on), then scan it."""
        try:
            st = os.fstat(fd)
        except OSError as exc:
            os.close(fd)
            self.error(exc, disk_path)
            return
        key = (st.st_dev, st.st_ino)
        todo: list[tuple[str, str, str]] = []
        stack.append((fd, key, todo))
        self.open_dirs.add(key)
        todo.extend(self.scan(fd, disk_path, path))

    def result(self) -> Inventory:
        inv = Inventory(self.entries)
        inv.walk_errors = self.errors  # type: ignore[attr-defined]
        return inv


def walk_fs(root: str | os.PathLike[str], *, map_root: tuple[str, str] | None = None, hash: bool = False,
            owners: OwnersArg = None, follow_symlinks: bool = False,
            on_error: Callable[[OSError], None] | None = None) -> Inventory:
    """Crawl ``root`` into a strict :class:`Inventory`.

    Directories are opened with ``O_DIRECTORY|O_NOFOLLOW`` relative to their
    parent's fd and listed with ``os.scandir(fd)``; entries are stat'ed
    relative to that fd without following symlinks. Names are decoded with
    ``os.fsdecode`` (``surrogateescape``). ``/`` and every ancestor of the
    (mapped) root are emitted too; an ancestor with no on-disk counterpart
    (above ``map_root``'s destination) is synthesised from the root's stat
    with inode 0.

    ``map_root=(src, dst)`` rewrites on-disk paths under ``src`` to ``dst``
    (``root`` must lie under ``src``). ``hash=True`` records sha256 of every
    regular file (1 MiB reads; beware sparse files are read in full).
    ``owners`` -- a :class:`Manifest`, a sidecar path, or a mapping of
    inventory path to ``(uid, gid[, sha256[, ctime]])`` -- overrides uid/gid
    and ctime, and supplies sha256 when ``hash`` is false. Symlinks get
    ``size = len(target)`` and the target verbatim from ``os.readlink``.
    ``follow_symlinks=True`` reports a link to a regular file as that file
    (its size, mtime, inode; hashed through the link); links to anything else
    stay links, so the walk never leaves ``root`` or visits a directory twice.
    A bind mount of an open ancestor is listed but not entered. Sockets,
    fifos and devices are skipped.

    An ``OSError`` on a directory skips its subtree; on an entry, skips the
    entry; a name or symlink target holding a tab, newline or carriage
    return (which the TSV cannot hold) is reported as ``EINVAL`` and skipped. Each is passed to ``on_error`` (which may re-raise to abort)
    and recorded as a string in the returned inventory's ``walk_errors``.
    """
    return _Walk(os.fspath(root), map_root, hash, owners, follow_symlinks, on_error).run()
