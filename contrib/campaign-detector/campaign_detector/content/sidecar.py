"""Sidecar TSVs: what a licensed reader *would* extract, declared by a scenario.

Until OpenEye/Schrodinger readers are reachable, synthetic scenarios declare
content facts next to their inventory and :func:`write` emits three TSVs
(inventory conventions: header row, UTF-8 + ``surrogateescape``, empty cell
= ``None``, rows sorted; never JSON)::

    ligands.tsv   path sha256 role name smiles inchikey inchikey14 scaffold stereo confidence canon record
    metrics.tsv   path sha256 key value unit scope cost
    mentions.tsv  path sha256 token kind

A scenario module opts in with a module-level ``CONTENT`` mapping from the
scenario's short name (the part after ``<module>.``) to a
:class:`SidecarBuilder` or a zero-argument callable returning one.
``sha256`` cells are copied from the built inventory, so a sidecar row
describes exactly the bytes the inventory hashed.

Fake InChIKeys (:func:`fake_inchikey`) are deterministic and format-valid
(``^[A-Z]{14}-[A-Z]{10}-[A-Z]$``): the 14-letter connectivity block comes
from ``sha256("ik1:" + SMILES with @, / and \\ removed)``, the 8 letters of
the second block from ``sha256("ik2:" + SMILES)``, followed by ``SA``
(standard, version A) and ``-N`` (neutral). Stereo variants of one SMILES
therefore share ``inchikey14`` but not the full key, as real keys do. No
cheminformatics toolkit is involved; SMILES strings are placeholders.
"""

from __future__ import annotations

import hashlib
import importlib
import os
from collections.abc import Callable
from dataclasses import dataclass, field

from ..inventory import Inventory, normalize_path
from ..synth import Scenario
from .model import CONFIDENCES, COSTS, MENTION_KINDS, ROLES, connectivity_block, read_tsv, write_tsv

LIGAND_COLUMNS: tuple[str, ...] = ("path", "sha256", "role", "name", "smiles", "inchikey", "inchikey14",
                                   "scaffold", "stereo", "confidence", "canon", "record")
METRIC_COLUMNS: tuple[str, ...] = ("path", "sha256", "key", "value", "unit", "scope", "cost")
MENTION_COLUMNS: tuple[str, ...] = ("path", "sha256", "token", "kind")
SIDECAR_FILES: dict[str, tuple[str, ...]] = {
    "ligands.tsv": LIGAND_COLUMNS, "metrics.tsv": METRIC_COLUMNS, "mentions.tsv": MENTION_COLUMNS,
}
"""Sidecar file names and their columns."""

FAKE_CANON = "fake-sidecar-v1"
"""``canon`` string of sidecar identities: SMILES are comparable only within it."""

_STEREO_CHARS = str.maketrans("", "", "@/\\")


def strip_stereo(smiles: str) -> str:
    """``smiles`` without ``@``, ``/`` and ``\\`` (a stand-in for stereo-free canonicalisation)."""
    return smiles.translate(_STEREO_CHARS)


def _letters(tag: str, text: str, n: int) -> str:
    digest = hashlib.sha256(f"{tag}:{text}".encode()).digest()
    return "".join(chr(65 + b % 26) for b in digest[:n])


def fake_inchikey(smiles: str) -> str:
    """Deterministic, format-valid fake InChIKey for ``smiles`` (see the module docstring)."""
    return f"{_letters('ik1', strip_stereo(smiles), 14)}-{_letters('ik2', smiles, 8)}SA-N"


@dataclass(frozen=True)
class LigandRow:
    """One declared ligand identity (a row of ``ligands.tsv`` without its sha)."""

    path: str
    role: str
    name: str | None
    smiles: str
    inchikey: str
    scaffold: str | None
    stereo: str
    confidence: str
    canon: str
    record: str


@dataclass(frozen=True)
class MetricRow:
    """One declared metric (a row of ``metrics.tsv`` without its sha)."""

    path: str
    key: str
    value: float
    unit: str
    scope: str
    cost: str


@dataclass(frozen=True)
class MentionRow:
    """One declared mention (a row of ``mentions.tsv`` without its sha)."""

    path: str
    token: str
    kind: str


@dataclass
class SidecarBuilder:
    """Collects content facts for the files of one synthetic inventory."""

    ligands: list[LigandRow] = field(default_factory=list)
    metrics: list[MetricRow] = field(default_factory=list)
    mentions: list[MentionRow] = field(default_factory=list)

    def ligand(self, path: str, smiles: str, *, role: str = "ligand", name: str | None = None,
               inchikey: str | None = None, scaffold: str | None = None, stereo: str | None = None,
               confidence: str = "high", canon: str = FAKE_CANON, record: str = "1") -> LigandRow:
        """Declare that ``path`` holds the molecule ``smiles`` (key defaults to :func:`fake_inchikey`)."""
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r} (expected one of {ROLES})")
        if confidence not in CONFIDENCES:
            raise ValueError(f"unknown confidence {confidence!r} (expected one of {CONFIDENCES})")
        if stereo is None:
            stereo = "specified" if strip_stereo(smiles) != smiles else "none"
        row = LigandRow(normalize_path(path), role, name, smiles, inchikey or fake_inchikey(smiles), scaffold,
                        stereo, confidence, canon, record)
        self.ligands.append(row)
        return row

    def metric(self, path: str, key: str, value: float, unit: str = "", *, scope: str = "run",
               cost: str = "small") -> MetricRow:
        """Declare a metric read from ``path``."""
        if cost not in COSTS:
            raise ValueError(f"unknown cost {cost!r} (expected one of {COSTS})")
        row = MetricRow(normalize_path(path), key, float(value), unit, scope, cost)
        self.metrics.append(row)
        return row

    def mention(self, path: str, token: str, kind: str = "candidate_id") -> MentionRow:
        """Declare that the text of ``path`` mentions ``token``."""
        if kind not in MENTION_KINDS:
            raise ValueError(f"unknown mention kind {kind!r} (expected one of {MENTION_KINDS})")
        row = MentionRow(normalize_path(path), token, kind)
        self.mentions.append(row)
        return row

    def paths(self) -> set[str]:
        """Every path any fact is declared for."""
        return {r.path for r in self.ligands} | {r.path for r in self.metrics} | {r.path for r in self.mentions}


ContentSource = SidecarBuilder | Callable[[], SidecarBuilder]


def content_for(scenario: Scenario) -> SidecarBuilder | None:
    """The :class:`SidecarBuilder` a scenario's module declares in ``CONTENT``, or ``None``."""
    module = importlib.import_module(scenario.build.__module__)
    table: dict[str, ContentSource] = getattr(module, "CONTENT", {}) or {}
    src = table.get(scenario.name.split(".", 1)[1])
    if src is None:
        return None
    return src if isinstance(src, SidecarBuilder) else src()


def write(source: Scenario | SidecarBuilder, out_dir: str | os.PathLike[str], *,
          inv: Inventory | None = None) -> dict[str, int]:
    """Write the three sidecar TSVs into ``out_dir``; returns rows written per file.

    For a :class:`~campaign_detector.synth.Scenario` the inventory is built
    and its declared content used (empty sidecars if it declares none). With
    an inventory every declared path must exist in it, and sha256 cells come
    from it; without one they are empty.
    """
    if isinstance(source, Scenario):
        inv = source.build() if inv is None else inv
        content = content_for(source) or SidecarBuilder()
    else:
        content = source
    if inv is not None:
        missing = sorted(p for p in content.paths() if p not in inv)
        if missing:
            raise ValueError(f"sidecar paths not in the inventory: {missing[:5]}")

    def sha(path: str) -> str | None:
        return inv.by_path[path].sha256 if inv is not None else None

    tables: dict[str, list[tuple[object, ...]]] = {
        "ligands.tsv": [(r.path, sha(r.path), r.role, r.name, r.smiles, r.inchikey, connectivity_block(r.inchikey),
                         r.scaffold, r.stereo, r.confidence, r.canon, r.record) for r in content.ligands],
        "metrics.tsv": [(r.path, sha(r.path), r.key, r.value, r.unit, r.scope, r.cost) for r in content.metrics],
        "mentions.tsv": [(r.path, sha(r.path), r.token, r.kind) for r in content.mentions],
    }
    os.makedirs(out_dir, exist_ok=True)
    counts = {}
    for name, columns in SIDECAR_FILES.items():
        rows = sorted(set(tables[name]), key=lambda row: tuple("" if v is None else str(v) for v in row))
        write_tsv(os.path.join(out_dir, name), columns, rows)
        counts[name] = len(rows)
    return counts


Row = dict[str, str | None]


@dataclass
class SidecarData:
    """Sidecar rows read back from a directory, indexed by path and by sha256."""

    ligands: list[Row]
    metrics: list[Row]
    mentions: list[Row]

    def __post_init__(self) -> None:
        self.by_path: dict[str, dict[str, list[Row]]] = {}
        self.by_sha: dict[str, dict[str, list[Row]]] = {}
        for table, rows in (("ligands", self.ligands), ("metrics", self.metrics), ("mentions", self.mentions)):
            for row in rows:
                self.by_path.setdefault(row["path"] or "", {}).setdefault(table, []).append(row)
                if row["sha256"]:
                    self.by_sha.setdefault(row["sha256"], {}).setdefault(table, []).append(row)

    def __len__(self) -> int:
        return len(self.ligands) + len(self.metrics) + len(self.mentions)

    def sha_of(self, path: str) -> str | None:
        """The sha256 the sidecar recorded for ``path`` (``None`` if absent or unhashed)."""
        for rows in self.by_path.get(path, {}).values():
            for row in rows:
                if row["sha256"]:
                    return row["sha256"]
        return None


def read(content_dir: str | os.PathLike[str]) -> SidecarData:
    """Read the sidecars in ``content_dir``; a missing file counts as empty."""
    tables: dict[str, list[Row]] = {}
    for name, columns in SIDECAR_FILES.items():
        path = os.path.join(content_dir, name)
        tables[name] = read_tsv(path, columns) if os.path.exists(path) else []
    return SidecarData(tables["ligands.tsv"], tables["metrics.tsv"], tables["mentions.tsv"])
