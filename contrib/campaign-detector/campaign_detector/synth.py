"""Deterministic synthetic inventories and the scenario data model.

:class:`TreeBuilder` assembles an :class:`~campaign_detector.inventory.Inventory`
entry by entry; :func:`md_campaign`, :func:`human_analysis` and the ``pick_by_*``
helpers lay down the fingerprints of an MD campaign, a human analysis
directory and the human's selections. :class:`Scenario` and
:class:`ExpectedOutcome` describe what the detector should report. Nothing in
this module uses randomness.
"""

from __future__ import annotations

import hashlib
import posixpath
import string
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from .features import T0, at, classify_path, id_token, workday
from .inventory import Entry, Inventory, normalize_path

if TYPE_CHECKING:
    from .detect import DetectionResult

__all__ = [
    "T0", "at", "workday", "TreeBuilder", "CampaignSpec", "ENGINE_PROFILES", "md_campaign",
    "AnalysisSpec", "human_analysis", "pick_by_copy", "pick_by_symlink", "pick_by_derived",
    "ExpectedOutcome", "Scenario", "compare",
]


@dataclass
class _Node:
    kind: str
    size: int
    mtime: int
    ctime: int
    uid: int
    gid: int
    inode: int = 0
    content_id: str | None = None
    target: str | None = None
    pinned: bool = False


class TreeBuilder:
    """Incrementally build an inventory.

    Relative paths are joined to ``root``; missing ancestor directories
    (up to ``/``) are created with the builder defaults. On :meth:`build` a
    directory's mtime becomes that of its newest direct child, as on a real
    filesystem; an ``mtime`` given to :meth:`dir` is a floor, and the builder
    default ``mtime`` is used only for empty directories.
    Inodes are assigned from 1000 in insertion order; a file's sha256 is
    ``sha256(b"cd:" + content_id)`` where ``content_id`` defaults to its path.
    """

    def __init__(self, root: str = "/vol1", *, uid: int = 1000, gid: int = 1000, mtime: int = T0) -> None:
        self.root = normalize_path(root)
        self.uid = uid
        self.gid = gid
        self.mtime = mtime
        self._nodes: dict[str, _Node] = {}
        self._next_inode = 1000
        self.dir(self.root)

    def _abs(self, path: str) -> str:
        return normalize_path(posixpath.join(self.root, path))

    def _add(self, path: str, node: _Node, *, new_inode: bool = True) -> str:
        if path in self._nodes:
            raise ValueError(f"path already exists: {path!r}")
        if path != "/":
            self.dir(posixpath.dirname(path))
        if new_inode:
            node.inode = self._next_inode
            self._next_inode += 1
        self._nodes[path] = node
        return path

    def dir(self, path: str, *, mtime: int | None = None, uid: int | None = None, gid: int | None = None) -> str:
        """Create a directory (and its ancestors); returns its absolute path.

        If it already exists, only the attributes given here are updated.
        """
        p = self._abs(path)
        node = self._nodes.get(p)
        if node is not None:
            if node.kind != "d":
                raise ValueError(f"not a directory: {p!r}")
            if mtime is not None:
                node.mtime = node.ctime = mtime
                node.pinned = True
            if uid is not None:
                node.uid = uid
            if gid is not None:
                node.gid = gid
            return p
        m = self.mtime if mtime is None else mtime
        return self._add(p, _Node("d", 0, m, m, self.uid if uid is None else uid,
                                  self.gid if gid is None else gid, pinned=mtime is not None))

    def file(self, path: str, *, size: int, mtime: int, uid: int | None = None, gid: int | None = None,
             content_id: str | None = None, ctime: int | None = None) -> str:
        """Create a regular file; returns its absolute path."""
        p = self._abs(path)
        return self._add(p, _Node("f", size, mtime, mtime if ctime is None else ctime,
                                  self.uid if uid is None else uid, self.gid if gid is None else gid,
                                  content_id=p if content_id is None else content_id))

    def symlink(self, path: str, target: str, *, mtime: int, uid: int | None = None) -> str:
        """Create a symlink storing ``target`` verbatim (may be relative)."""
        p = self._abs(path)
        return self._add(p, _Node("l", len(target), mtime, mtime, self.uid if uid is None else uid,
                                  self.gid, target=target))

    def copy(self, src: str, dst: str, *, mtime: int, uid: int | None = None) -> str:
        """Copy a file: new inode, same size and content (hence same sha256)."""
        s = self._nodes[self._abs(src)]
        if s.kind != "f":
            raise ValueError(f"can only copy files: {src!r}")
        return self.file(dst, size=s.size, mtime=mtime, uid=uid, content_id=s.content_id)

    def hardlink(self, src: str, dst: str) -> str:
        """Add a second name for a file: same inode, attributes and content."""
        s = self._nodes[self._abs(src)]
        if s.kind != "f":
            raise ValueError(f"can only hardlink files: {src!r}")
        return self._add(self._abs(dst), s, new_inode=False)

    def build(self) -> Inventory:
        """Freeze the tree into an :class:`Inventory` (the builder stays usable)."""
        names: dict[int, int] = {}
        subdirs: dict[str, int] = {}
        for p, node in self._nodes.items():
            names[id(node)] = names.get(id(node), 0) + 1
            if node.kind == "d" and p != "/":
                parent = posixpath.dirname(p)
                subdirs[parent] = subdirs.get(parent, 0) + 1
        # Deepest first, so a directory sees its subdirectories' final mtimes.
        mtimes = {p: n.mtime for p, n in self._nodes.items() if n.kind != "d"}
        newest: dict[str, int] = {}
        for p in sorted(self._nodes, key=lambda q: 0 if q == "/" else -q.count("/")):
            node = self._nodes[p]
            if node.kind == "d":
                m = newest.get(p, node.mtime)
                mtimes[p] = max(m, node.mtime) if node.pinned else m
            if p != "/":
                parent = posixpath.dirname(p)
                newest[parent] = max(newest.get(parent, mtimes[p]), mtimes[p])
        entries = []
        for p, node in self._nodes.items():
            if node.kind == "d":
                entries.append(Entry(p, "d", 0, mtimes[p], mtimes[p], node.uid, node.gid, node.inode,
                                     2 + subdirs.get(p, 0)))
            elif node.kind == "l":
                entries.append(Entry(p, "l", node.size, node.mtime, node.ctime, node.uid, node.gid,
                                     node.inode, 1, target=node.target))
            else:
                sha = hashlib.sha256(b"cd:" + str(node.content_id).encode()).hexdigest()
                entries.append(Entry(p, "f", node.size, node.mtime, node.ctime, node.uid, node.gid,
                                     node.inode, names[id(node)], sha256=sha))
        return Inventory(entries)


# --------------------------------------------------------------------------
# MD campaigns
# --------------------------------------------------------------------------

ENGINE_PROFILES: dict[str, tuple[str, ...]] = {
    "amber": ("complex.prmtop", "prod.in", "prod{:03d}.nc", "prod.rst7", "prod{:03d}.out", "slurm-{jobid}.out"),
    "gromacs": ("topol.top", "md.mdp", "traj{:03d}.xtc", "state.cpt", "md.log", "ener.edr", "slurm-{jobid}.out"),
    "desmond": ("system.cms", "config.cfg", "traj{:03d}.dcd", "checkpoint.chk", "run.log", "job.o{jobid}"),
    "namd": ("sys.psf", "prod.inp", "prod{:03d}.dcd", "prod.coor", "prod.log", "slurm-{jobid}.out"),
    "desmond_trj": ("md-in.cms", "md.msj", "md.cfg", "md_trj/frame{:03d}", "md_trj/clickme.dtr", "md-out.cms",
                    "md.ene", "md.log", "md.cpt", "job.o{jobid}"),
}
"""File names of one run directory per engine: ``{:03d}`` = one per chunk
(1-based), ``{jobid}`` = scheduler job id, anything else = one file.
``desmond_trj`` is the real Desmond layout: ``-in.cms``/``-out.cms``, ``.msj``,
``.ene`` and an ``md_trj/`` directory of extension-less ``frame###`` files."""

_CLASS_SIZES = {"TOPO": 4_000_000, "INPUT": 2_048, "RESTART": 3_000_000, "LOG": 51_200, "SCHED": 51_200}
_JOBID_BASE = 4_100_000


@dataclass(frozen=True)
class CampaignSpec:
    """Shape of one synthetic MD campaign laid down by :func:`md_campaign`.

    Candidates are ``candidate_fmt.format(i)`` for ``i`` in 1..``n_candidates``
    minus ``skip``. ``inner_fmt`` adds one nested level of ``n_inner`` run dirs
    per candidate: integer formats (``"rep{}"``) get ``j`` = 1..n_inner, float
    formats (``"lambda_{:.2f}"``) get ``(j-1)/(n_inner-1)`` (0.0 when n_inner=1).
    """

    engine: str = "amber"
    n_candidates: int = 24
    candidate_fmt: str = "run_lig{:03d}"
    inner_fmt: str | None = None
    n_inner: int = 1
    n_chunks: int = 10
    chunk_interval_s: int = 21600
    chunk_size: int = 2_000_000_000
    uid: int = 2001
    start: int = at(0, 3)
    stagger_s: int = 900
    jitter_s: int = 0
    skip: frozenset[int] = frozenset()
    boilerplate: tuple[str, ...] = ("prod.in",)


def _inner_names(spec: CampaignSpec) -> list[str | None]:
    if spec.inner_fmt is None:
        return [None]
    specs = [f[2] or "" for f in string.Formatter().parse(spec.inner_fmt) if f[1] is not None]
    if any(s.endswith(("f", "e", "g", "%")) for s in specs):
        denom = max(spec.n_inner - 1, 1)
        return [spec.inner_fmt.format(j / denom) for j in range(spec.n_inner)]
    return [spec.inner_fmt.format(j) for j in range(1, spec.n_inner + 1)]


def md_campaign(tb: TreeBuilder, root: str, spec: CampaignSpec = CampaignSpec()) -> list[str]:
    """Lay down an MD campaign under ``root``; returns the candidate dir names.

    Chunk ``k`` (0-based) of the ``c``-th existing candidate (0-based, ``skip``
    excluded) and inner run ``j`` (0-based) has mtime ``start + c*stagger_s +
    j*60 + k*chunk_interval_s + (jitter_s if k odd else -jitter_s)``; per-chunk
    logs share it; single files get chunk 0's mtime - 60 s. Files named in
    ``spec.boilerplate`` share one content id per campaign.
    """
    profile = ENGINE_PROFILES[spec.engine]
    root = tb.dir(root, uid=spec.uid)
    names: list[str] = []
    inner_names = _inner_names(spec)
    indices = [i for i in range(1, spec.n_candidates + 1) if i not in spec.skip]
    for c, i in enumerate(indices):
        cand = spec.candidate_fmt.format(i)
        names.append(cand)
        cand_dir = tb.dir(posixpath.join(root, cand), uid=spec.uid)
        for j, inner in enumerate(inner_names):
            run_dir = cand_dir if inner is None else tb.dir(posixpath.join(cand_dir, inner), uid=spec.uid)
            t0 = spec.start + c * spec.stagger_s + j * 60
            jobid = _JOBID_BASE + (i - 1) * len(inner_names) + j
            for pattern in profile:
                if "{:03d}" in pattern:
                    for k in range(spec.n_chunks):
                        jitter = spec.jitter_s if k % 2 else -spec.jitter_s
                        name = pattern.format(k + 1)
                        _run_file(tb, run_dir, name, t0 + k * spec.chunk_interval_s + jitter, root, spec)
                else:
                    _run_file(tb, run_dir, pattern.format(jobid=jobid), t0 - 60, root, spec)
    return names


def _run_file(tb: TreeBuilder, run_dir: str, name: str, mtime: int, root: str, spec: CampaignSpec) -> None:
    path = posixpath.join(run_dir, name)
    cls = classify_path(path)
    size = spec.chunk_size if cls == "TRAJ" else _CLASS_SIZES.get(cls, 1_024)
    content_id = f"{root}:boilerplate:{name}" if name in spec.boilerplate else None
    tb.file(path, size=size, mtime=mtime, uid=spec.uid, content_id=content_id)


# --------------------------------------------------------------------------
# Human curation
# --------------------------------------------------------------------------

_DERIVED_SIZES = {".xlsx": 48_000, ".pptx": 2_400_000, ".png": 60_000, ".ipynb": 180_000,
                  ".md": 2_000, ".txt": 3_000, ".pdf": 350_000, ".csv": 12_000}


@dataclass(frozen=True)
class AnalysisSpec:
    """A human analysis directory laid down by :func:`human_analysis`."""

    uid: int = 3002
    first_workday: int = 15
    bursts: int = 3
    burst_gap_days: int = 3
    dirname: str = "analysis"
    files: tuple[str, ...] = ("README.md", "notes.txt", "summary.xlsx", "fig3_rmsd.png", "top10_final.pptx",
                              "hits.ipynb")


def human_analysis(tb: TreeBuilder, parent: str, spec: AnalysisSpec = AnalysisSpec()) -> str:
    """Create ``parent/spec.dirname`` holding ``spec.files``; returns its path.

    File ``n`` goes to burst ``b = n % bursts`` on
    ``workday(first_workday + b*burst_gap_days)`` at 10:00 + 25 min x its slot
    within the burst, so every file lands in weekday working hours.
    """
    first = at(workday(spec.first_workday), 10)
    d = tb.dir(posixpath.join(tb.dir(parent), spec.dirname), uid=spec.uid, mtime=first)
    for n, name in enumerate(spec.files):
        b, slot = n % spec.bursts, n // spec.bursts
        mtime = at(workday(spec.first_workday + b * spec.burst_gap_days), 10, 25 * slot)
        size = _DERIVED_SIZES.get(posixpath.splitext(name)[1].lower(), 20_000)
        tb.file(posixpath.join(d, name), size=size, mtime=mtime, uid=spec.uid)
    return d


def _pick_name(fmt: str, cid: str) -> str:
    return fmt.format(cid=cid, id=id_token(cid) or cid)


def pick_by_copy(tb: TreeBuilder, campaign_root: str, dst_dir: str, cids: Iterable[str], *,
                 src_name: str = "prod010.nc", rename: str = "{id}_best.nc", uid: int, mtime: int) -> list[str]:
    """Copy ``campaign_root/<cid>/src_name`` to ``dst_dir/rename`` for each candidate.

    ``rename`` may use ``{cid}`` (candidate dir name, ``run_lig012``) and
    ``{id}`` (its id token, ``lig012``). The n-th copy gets ``mtime + 60*n``.
    """
    out = []
    for n, cid in enumerate(cids):
        src = posixpath.join(tb.dir(campaign_root), cid, src_name)
        out.append(tb.copy(src, posixpath.join(tb.dir(dst_dir), _pick_name(rename, cid)), mtime=mtime + 60 * n, uid=uid))
    return out


def pick_by_symlink(tb: TreeBuilder, dst_dir: str, campaign_root: str, cids: Iterable[str], *, uid: int,
                    mtime: int, src_name: str = "prod010.nc", link_name: str = "{id}_traj") -> list[str]:
    """Create ``dst_dir/link_name`` -> relative path of ``campaign_root/<cid>/src_name``.

    ``link_name`` takes the same placeholders as :func:`pick_by_copy`; the n-th
    link gets ``mtime + 60*n``.
    """
    d = tb.dir(dst_dir)
    out = []
    for n, cid in enumerate(cids):
        rel = posixpath.relpath(posixpath.join(tb.dir(campaign_root), cid, src_name), d)
        out.append(tb.symlink(posixpath.join(d, _pick_name(link_name, cid)), rel, mtime=mtime + 60 * n, uid=uid))
    return out


def pick_by_derived(tb: TreeBuilder, dst_dir: str, cids: Iterable[str], *, suffix: str = "_rmsd.png", uid: int,
                    mtime: int, size: int = 40_000) -> list[str]:
    """Create a derived artifact ``dst_dir/<id><suffix>`` per candidate (``lig029_rmsd.png``).

    ``<id>`` is the candidate's id token (the dir name if it has none); the
    n-th file gets ``mtime + 60*n``.
    """
    d = tb.dir(dst_dir)
    return [tb.file(posixpath.join(d, _pick_name("{id}", cid) + suffix), size=size, mtime=mtime + 60 * n, uid=uid)
            for n, cid in enumerate(cids)]


# --------------------------------------------------------------------------
# Scenarios and expectations
# --------------------------------------------------------------------------

LABELS: tuple[str, ...] = ("picked", "not_picked", "unknown")
"""Candidate labels the detector assigns."""


def _fs(items: Iterable[str]) -> frozenset[str]:
    return frozenset(items)


@dataclass(frozen=True)
class ExpectedOutcome:
    """What the detector should report for a scenario.

    ``campaign_roots`` must equal the detected roots exactly. For a root listed
    in ``picked``/``not_picked``/``unknown`` that label's candidate set must
    match exactly; unlisted labels are unconstrained unless ``rest[root]``
    names a label, in which case every candidate not listed explicitly must
    carry it. ``present[root]`` ids must appear among the report's candidates.
    """

    campaign_roots: frozenset[str]
    picked: Mapping[str, frozenset[str]] = field(default_factory=dict)
    not_picked: Mapping[str, frozenset[str]] = field(default_factory=dict)
    unknown: Mapping[str, frozenset[str]] = field(default_factory=dict)
    rest: Mapping[str, str] = field(default_factory=dict)
    present: Mapping[str, frozenset[str]] = field(default_factory=dict)

    @staticmethod
    def no_campaign() -> ExpectedOutcome:
        """No campaign root may be detected."""
        return ExpectedOutcome(campaign_roots=frozenset())

    @staticmethod
    def campaign_no_selection(root: str, cids: Iterable[str] = ()) -> ExpectedOutcome:
        """Exactly one campaign at ``root``; nothing picked; ``cids`` must be candidates."""
        root = normalize_path(root)
        return ExpectedOutcome(campaign_roots=frozenset({root}), picked={root: frozenset()},
                               present={root: _fs(cids)} if cids else {})

    @staticmethod
    def selection(root: str, picked: Iterable[str], not_picked: Iterable[str] = (), unknown: Iterable[str] = (),
                  rest: str | None = None) -> ExpectedOutcome:
        """Exactly one campaign at ``root`` with the given labels.

        ``picked`` is always exact; ``not_picked``/``unknown`` are exact when
        non-empty; ``rest`` ("not_picked" or "unknown") labels all others.
        """
        if rest not in (None, "not_picked", "unknown"):
            raise ValueError(f"rest must be None, 'not_picked' or 'unknown', not {rest!r}")
        root = normalize_path(root)
        np_, unk = _fs(not_picked), _fs(unknown)
        return ExpectedOutcome(
            campaign_roots=frozenset({root}),
            picked={root: _fs(picked)},
            not_picked={root: np_} if np_ else {},
            unknown={root: unk} if unk else {},
            rest={root: rest} if rest else {},
        )


@dataclass(frozen=True)
class Scenario:
    """A named synthetic inventory with its expected detection outcome.

    ``known_gap`` (``"<heuristic>: <why>"``) marks a scenario the detector is
    known to get wrong; tests then expect the mismatch.
    """

    name: str
    kind: Literal["positive", "negative"]
    description: str
    build: Callable[[], Inventory]
    expected: ExpectedOutcome
    known_gap: str | None = None


def _fmt(ids: Iterable[str]) -> str:
    return "{" + ", ".join(sorted(ids)) + "}"


def compare(expected: ExpectedOutcome, result: DetectionResult) -> list[str]:
    """Human-readable mismatches between ``expected`` and ``result`` (empty = match)."""
    out: list[str] = []
    got_roots = set(result.campaign_roots)
    if got_roots != set(expected.campaign_roots):
        out.append(f"campaign roots: expected {_fmt(expected.campaign_roots)}, got {_fmt(got_roots)}")
    reports = {r.root: r for r in result.campaigns}
    constrained = set(expected.picked) | set(expected.not_picked) | set(expected.unknown) | set(expected.rest) \
        | set(expected.present)
    for root in sorted(constrained):
        report = reports.get(root)
        if report is None:
            out.append(f"{root}: no campaign report to check labels against")
            continue
        got = {"picked": report.picked(), "not_picked": report.not_picked(), "unknown": report.unknown()}
        listed = {label: set(getattr(expected, label).get(root, ())) for label in LABELS}
        cands = {c.id for c in report.candidates}
        missing = (set(expected.present.get(root, ())) | set().union(*listed.values())) - cands
        if missing:
            out.append(f"{root}: expected candidates not found: {_fmt(missing)}")
        rest = expected.rest.get(root)
        for label in LABELS:
            want = set(listed[label])
            if rest == label:
                want |= cands - set().union(*listed.values())
            elif root not in getattr(expected, label) and rest is None:
                continue
            if want != got[label]:
                extra, lacking = got[label] - want, want - got[label]
                detail = "; ".join(s for s in (f"unexpected {_fmt(extra)}" if extra else "",
                                               f"missing {_fmt(lacking)}" if lacking else "") if s)
                out.append(f"{root}: {label} mismatch: {detail}")
    return out
