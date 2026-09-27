"""The inventory table: one row per file, directory or symlink.

An :class:`Inventory` is the only input the featurizer and detector read. It
mirrors what a metadata crawler emits and never needs file contents; the
optional ``sha256`` column is used when the crawler hashed a file.
"""

from __future__ import annotations

import io
import os
import posixpath
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TextIO

KINDS: tuple[str, ...] = ("f", "d", "l")
"""Entry kinds: regular file, directory, symbolic link."""

COLUMNS: tuple[str, ...] = (
    "path", "kind", "size", "mtime", "ctime", "uid", "gid", "inode", "nlink", "sha256", "target",
)
"""Column order of the TSV serialisation (also the :class:`Entry` field order)."""

_INT_COLUMNS = frozenset({"size", "mtime", "ctime", "uid", "gid", "inode", "nlink"})
_OPTIONAL_COLUMNS = frozenset({"sha256", "target"})


def normalize_path(p: str) -> str:
    """Return ``p`` as a normalized absolute POSIX path.

    Uses :func:`posixpath.normpath`, strips trailing slashes and collapses a
    leading ``//``; the root is ``"/"``. Raises ``ValueError`` for relative paths.
    """
    if not p.startswith("/"):
        raise ValueError(f"path must be absolute: {p!r}")
    norm = posixpath.normpath(p)
    if norm.startswith("//"):
        norm = "/" + norm.lstrip("/")
    return norm


@dataclass(frozen=True, slots=True)
class Entry:
    """One inventory row.

    ``size`` is 0 for directories and ``len(target)`` for symlinks. ``target``
    is the symlink target exactly as stored on disk (possibly relative).
    """

    path: str
    kind: str
    size: int
    mtime: int
    ctime: int
    uid: int
    gid: int
    inode: int
    nlink: int
    sha256: str | None = None
    target: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"bad kind {self.kind!r} for {self.path!r}")
        if normalize_path(self.path) != self.path:
            raise ValueError(f"path is not normalized: {self.path!r}")

    @property
    def name(self) -> str:
        """Last path component (``""`` for the root)."""
        return posixpath.basename(self.path)

    @property
    def parent(self) -> str | None:
        """Path of the containing directory, or ``None`` for the root."""
        return None if self.path == "/" else posixpath.dirname(self.path)

    @property
    def stem(self) -> str:
        """Name without its last suffix (``prod001.nc`` -> ``prod001``)."""
        return posixpath.splitext(self.name)[0]

    @property
    def ext(self) -> str:
        """Lower-cased last suffix including the dot, ``""`` if none."""
        return posixpath.splitext(self.name)[1].lower()

    def resolved_target(self) -> str | None:
        """Absolute normalized symlink target, or ``None`` for non-links."""
        if self.kind != "l" or not self.target or self.parent is None:
            return None
        return normalize_path(posixpath.join(self.parent, self.target))


class Inventory:
    """A strict, indexed collection of :class:`Entry` rows.

    Every entry except ``"/"`` must have its parent directory present, so a
    crawler of ``/vol3`` also emits ``/`` and ``/vol3`` rows. Duplicate paths
    raise ``ValueError``. ``by_inode`` indexes every entry; inode numbers are
    only unique within one filesystem, so matches across volumes can collide.
    """

    def __init__(self, entries: Iterable[Entry]) -> None:
        self.by_path: dict[str, Entry] = {}
        for e in entries:
            if e.path in self.by_path:
                raise ValueError(f"duplicate path: {e.path!r}")
            self.by_path[e.path] = e
        self._sorted: list[Entry] = [self.by_path[p] for p in sorted(self.by_path)]
        self.by_sha: dict[str, list[Entry]] = {}
        self.by_inode: dict[int, list[Entry]] = {}
        self._children: dict[str, list[Entry]] = {}
        for e in self._sorted:
            parent = e.parent
            if parent is not None:
                pe = self.by_path.get(parent)
                if pe is None or pe.kind != "d":
                    raise ValueError(f"parent directory missing for {e.path!r}")
                self._children.setdefault(parent, []).append(e)
            if e.sha256:
                self.by_sha.setdefault(e.sha256, []).append(e)
            self.by_inode.setdefault(e.inode, []).append(e)
        for kids in self._children.values():
            kids.sort(key=lambda k: k.name)

    def children(self, path: str) -> list[Entry]:
        """Direct children of ``path`` sorted by name (empty for non-dirs)."""
        return list(self._children.get(path, ()))

    def parent(self, path: str) -> Entry | None:
        """The parent directory entry of ``path``, or ``None`` for the root."""
        e = self.by_path[path]
        return None if e.parent is None else self.by_path[e.parent]

    def subtree(self, root: str) -> Iterator[Entry]:
        """Yield ``root`` and all its descendants in preorder (children by name)."""
        stack = [self.by_path[root]]
        while stack:
            e = stack.pop()
            yield e
            stack.extend(reversed(self._children.get(e.path, ())))

    def dirs(self) -> list[Entry]:
        """All directories, sorted by path."""
        return [e for e in self._sorted if e.kind == "d"]

    def files(self) -> list[Entry]:
        """All regular files, sorted by path."""
        return [e for e in self._sorted if e.kind == "f"]

    def links(self) -> list[Entry]:
        """All symlinks, sorted by path."""
        return [e for e in self._sorted if e.kind == "l"]

    def __iter__(self) -> Iterator[Entry]:
        return iter(self._sorted)

    def __len__(self) -> int:
        return len(self._sorted)

    def __contains__(self, path: object) -> bool:
        return path in self.by_path

    @classmethod
    def from_tsv(cls, src: str | os.PathLike[str] | TextIO) -> Inventory:
        """Read an inventory written by :meth:`to_tsv` (path or open text stream).

        A path is opened with ``newline="\\n"`` so only ``\\n`` ends a row and a
        carriage return inside a name survives; an open stream must do the same.
        """
        if isinstance(src, (str, os.PathLike)):
            with open(src, encoding="utf-8", errors="surrogateescape", newline="\n") as fh:
                return cls._read(fh)
        return cls._read(src)

    @classmethod
    def _read(cls, fh: TextIO) -> Inventory:
        header = fh.readline().rstrip("\n").split("\t")
        if tuple(header) != COLUMNS:
            raise ValueError(f"unexpected TSV header: {header!r}")
        entries = []
        for lineno, line in enumerate(fh, start=2):
            line = line.rstrip("\n")
            if not line:
                continue
            cells = line.split("\t")
            if len(cells) != len(COLUMNS):
                raise ValueError(f"line {lineno}: expected {len(COLUMNS)} columns, got {len(cells)}")
            row: dict[str, object] = {}
            for col, cell in zip(COLUMNS, cells):
                if col in _INT_COLUMNS:
                    row[col] = int(cell)
                elif col in _OPTIONAL_COLUMNS:
                    row[col] = cell or None
                else:
                    row[col] = cell
            entries.append(Entry(**row))  # type: ignore[arg-type]
        return cls(entries)

    def to_tsv(self, dst: str | os.PathLike[str] | TextIO) -> None:
        """Write a header row then one row per entry sorted by path.

        ``None`` is written as an empty cell. A tab or newline inside a path
        or target raises ``ValueError``. Files are UTF-8 with
        ``errors="surrogateescape"`` so undecodable names round-trip.
        """
        if isinstance(dst, (str, os.PathLike)):
            with open(dst, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
                self._write(fh)
        else:
            self._write(dst)

    def _write(self, fh: TextIO) -> None:
        buf = io.StringIO()
        buf.write("\t".join(COLUMNS) + "\n")
        for e in self._sorted:
            cells = []
            for col in COLUMNS:
                value = getattr(e, col)
                cell = "" if value is None else str(value)
                if "\t" in cell or "\n" in cell:
                    raise ValueError(f"tab or newline in {col} of {e.path!r}")
                cells.append(cell)
            buf.write("\t".join(cells) + "\n")
        fh.write(buf.getvalue())
