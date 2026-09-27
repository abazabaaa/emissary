"""Vendor-neutral schema shared by the detector and every content reader.

This module imports nothing but the standard library, so a reader service can
import it unchanged under ``$SCHRODINGER/run python3`` (3.11), an OpenEye
virtualenv or a plain RDKit/MDAnalysis venv. Readers work **per file**: a
:class:`FileRef` goes in, a :class:`ReaderResult` (ligand identities,
metrics, mentions, flags) comes out. Aggregation per candidate and every use
of the facts as detector evidence happen on the detector side.

The TSV helpers at the bottom are the one serialisation of this schema used
by the prototype (sidecars, result cache, winner rows): header row, UTF-8
with ``surrogateescape``, empty cell = ``None``, backslash escapes for tab,
newline, carriage return and backslash. No JSON or YAML files are written.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, TextIO, runtime_checkable

Cost = Literal["header", "small", "large"]
"""How much of a file a reader touches: header bytes, the whole (small) file, or a trajectory scan."""

COSTS: tuple[str, ...] = ("header", "small", "large")
"""Costs from cheapest to most expensive (index = rank)."""

FILE_CLASSES: tuple[str, ...] = (
    "TOPO", "INPUT", "TRAJ", "RESTART", "LOG", "SCHED", "STRUCT", "RESULT", "DERIVED", "OTHER",
)
"""Content file classes; a superset of the detector's MD classes (which stay unchanged)."""

CONFIDENCES: tuple[str, ...] = ("low", "medium", "high")
"""Identity confidences from weakest to strongest (index = rank)."""

ROLES: tuple[str, ...] = ("ligand", "ligand_a", "ligand_b", "cofactor", "cocrystal")
"""All ligand roles (``ligand_a``/``ligand_b`` are the two ends of a relative-FEP edge)."""

LIGAND_ROLES: frozenset[str] = frozenset({"ligand", "ligand_a", "ligand_b"})
"""Roles that identify what a candidate simulated (cofactors and co-crystal ligands do not)."""

MENTION_KINDS: tuple[str, ...] = ("candidate_id", "compound_id", "smiles", "inchikey")
"""What a textual mention names."""

UNITS: tuple[str, ...] = ("ligand", "edge", "leg", "unknown")
"""What one candidate directory stands for."""


def cost_rank(cost: str) -> int:
    """Rank of ``cost`` in :data:`COSTS` (``ValueError`` if unknown)."""
    return COSTS.index(cost)


def confidence_rank(confidence: str | None) -> int:
    """Rank of ``confidence`` in :data:`CONFIDENCES`; unknown or ``None`` ranks below ``low``."""
    return CONFIDENCES.index(confidence) if confidence in CONFIDENCES else -1


def connectivity_block(inchikey: str | None) -> str | None:
    """First (14-character connectivity) block of an InChIKey, or ``None``."""
    if not inchikey:
        return None
    return inchikey.split("-", 1)[0] or None


def candidate_key(root: str, candidate_id: str) -> str:
    """The global key of candidate ``candidate_id`` of campaign ``root``."""
    return f"{root}::{candidate_id}"


@dataclass(frozen=True, slots=True)
class FileRef:
    """One file (or Desmond ``_trj`` directory) handed to readers.

    ``companions`` are paths a context reader needs next to this one, e.g.
    the topology for a trajectory or the ``-out.cms`` for a ``_trj`` dir.
    """

    path: str
    sha256: str | None
    size: int
    mtime: int
    file_class: str
    fmt: str
    companions: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateRecord:
    """A candidate of one detected campaign plus its file manifest.

    ``files`` maps a file class to the candidate's refs of that class (any
    depth below ``path``, sorted by path); ``replicas`` are relative paths of
    replica or lambda sub-directories; ``unit`` is one of :data:`UNITS`.
    ``label`` is the label of the detection pass that built the record.
    """

    root: str
    candidate_id: str
    path: str
    engine: str
    era: int
    t_start: int
    t_end: int
    label: str
    unit: str
    replicas: tuple[str, ...]
    files: Mapping[str, tuple[FileRef, ...]]

    @property
    def key(self) -> str:
        """Globally unique candidate key ``"<root>::<candidate id>"``."""
        return candidate_key(self.root, self.candidate_id)

    def all_files(self) -> list[FileRef]:
        """Every ref of every class, sorted by path."""
        return sorted((r for refs in self.files.values() for r in refs), key=lambda r: r.path)


@dataclass(frozen=True)
class LigandIdentity:
    """A molecule found in a file, with provenance.

    ``inchikey`` is the join key across campaigns; ``inchikey14`` its
    connectivity block (tolerates stereo/protonation differences). ``smiles``
    is display-only and comparable only within one ``canon``. ``stereo`` is
    ``specified``, ``partial``, ``none`` or ``perceived_3d``; ``confidence``
    one of :data:`CONFIDENCES`.
    """

    role: str
    name: str | None
    inchikey: str | None
    inchikey14: str | None
    smiles: str | None
    scaffold: str | None
    canon: str
    stereo: str
    confidence: str
    source_path: str
    source_record: str


@dataclass(frozen=True)
class Metric:
    """A numeric fact read from one file (``scope``: file, run, edge or node)."""

    key: str
    value: float
    unit: str
    source_path: str
    cost: str
    scope: str


@dataclass(frozen=True)
class Mention:
    """A token found in text (``kind`` in :data:`MENTION_KINDS`)."""

    token: str
    kind: str
    source_path: str


@dataclass
class ReaderResult:
    """Everything one reader extracted from one file.

    ``flags`` are machine-readable caveats (``bond_orders_perceived``,
    ``no_normal_termination``, ``truncated``...); ``errors`` are failures.
    """

    reader: str
    reader_version: str
    toolkit: str
    toolkit_version: str
    input_path: str
    input_sha256: str | None
    cost: str
    license_feature: str | None = None
    ligands: list[LigandIdentity] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    mentions: list[Mention] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0


@runtime_checkable
class Reader(Protocol):
    """A per-file content reader.

    ``can_read`` must be cheap (no file I/O beyond a header); ``read`` may
    raise, in which case the registry records the error on an empty result.
    """

    name: str
    version: str
    cost: str

    def can_read(self, ref: FileRef) -> bool:
        """True if this reader understands ``ref``."""
        ...

    def read(self, ref: FileRef) -> ReaderResult:
        """Extract facts from ``ref``."""
        ...


# --------------------------------------------------------------------------
# TSV serialisation
# --------------------------------------------------------------------------

_ESCAPES = {"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r"}
_UNESCAPES = {"\\": "\\", "t": "\t", "n": "\n", "r": "\r"}


def encode_cell(value: object) -> str:
    """One TSV cell: ``None`` -> empty, floats via ``repr`` (exact round trip), escapes applied."""
    if value is None:
        return ""
    text = repr(value) if isinstance(value, float) else str(value)
    return "".join(_ESCAPES.get(ch, ch) for ch in text)


def decode_cell(cell: str) -> str | None:
    """Inverse of :func:`encode_cell` for strings (empty cell -> ``None``)."""
    if cell == "":
        return None
    if "\\" not in cell:
        return cell
    out: list[str] = []
    it = iter(cell)
    for ch in it:
        if ch == "\\":
            nxt = next(it, "")
            out.append(_UNESCAPES.get(nxt, "\\" + nxt))
        else:
            out.append(ch)
    return "".join(out)


def write_tsv(dst: str | os.PathLike[str] | TextIO, columns: Sequence[str],
              rows: Iterable[Sequence[object]]) -> None:
    """Write a header row then ``rows`` (each exactly as long as ``columns``)."""
    buf = io.StringIO()
    buf.write("\t".join(columns) + "\n")
    for row in rows:
        if len(row) != len(columns):
            raise ValueError(f"row has {len(row)} cells, expected {len(columns)}: {row!r}")
        buf.write("\t".join(encode_cell(v) for v in row) + "\n")
    if isinstance(dst, (str, os.PathLike)):
        with open(dst, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.write(buf.getvalue())
    else:
        dst.write(buf.getvalue())


def read_tsv(src: str | os.PathLike[str] | TextIO, columns: Sequence[str]) -> list[dict[str, str | None]]:
    """Read a TSV written by :func:`write_tsv`; the header must equal ``columns``."""
    if isinstance(src, (str, os.PathLike)):
        with open(src, encoding="utf-8", errors="surrogateescape", newline="") as fh:
            return read_tsv(fh, columns)
    header = src.readline().rstrip("\n").split("\t")
    if tuple(header) != tuple(columns):
        raise ValueError(f"unexpected TSV header {header!r}, expected {list(columns)!r}")
    out = []
    for lineno, line in enumerate(src, start=2):
        line = line.rstrip("\n")
        if not line:
            continue
        cells = line.split("\t")
        if len(cells) != len(columns):
            raise ValueError(f"line {lineno}: expected {len(columns)} columns, got {len(cells)}")
        out.append({c: decode_cell(v) for c, v in zip(columns, cells, strict=True)})
    return out
