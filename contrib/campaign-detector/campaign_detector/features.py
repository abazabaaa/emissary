"""Directory-shape featurizer.

Everything here is computed from inventory metadata alone. Time is handled as
integer epoch seconds with a fixed offset (no ``datetime``, no local timezone
lookups) so results are identical on every machine.
"""

from __future__ import annotations

import posixpath
import re
import statistics
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from .inventory import Entry, Inventory

# --------------------------------------------------------------------------
# Time model
# --------------------------------------------------------------------------

T0 = 1599436800
"""Monday 2020-09-07 00:00:00 UTC; day 0 of the synthetic calendar."""
TZ_OFFSET_S = 0
"""Default offset (seconds east of UTC) applied before computing hour/weekday."""
WORK_START_H = 8
"""First working hour (inclusive)."""
WORK_END_H = 18
"""End of the working day (exclusive)."""


def local_hour(ts: int, tz_offset_s: int = TZ_OFFSET_S) -> int:
    """Hour of day (0-23) of ``ts`` shifted by ``tz_offset_s``."""
    return ((ts + tz_offset_s) % 86400) // 3600


def weekday(ts: int, tz_offset_s: int = TZ_OFFSET_S) -> int:
    """Day of week of ``ts`` shifted by ``tz_offset_s`` (0 = Monday)."""
    return (((ts + tz_offset_s) // 86400) + 3) % 7


def is_working_hours(ts: int, tz_offset_s: int = TZ_OFFSET_S) -> bool:
    """True on Monday-Friday between ``WORK_START_H`` and ``WORK_END_H``."""
    return weekday(ts, tz_offset_s) < 5 and WORK_START_H <= local_hour(ts, tz_offset_s) < WORK_END_H


def era(ts: int) -> int:
    """Calendar year (UTC) of ``ts``."""
    return time.gmtime(ts).tm_year


def at(day: int, hour: float, minute: int = 0) -> int:
    """Epoch seconds of ``day`` days after ``T0`` at ``hour``:``minute`` UTC."""
    return T0 + day * 86400 + round(hour * 3600) + minute * 60


def workday(k: int) -> int:
    """Day number of the ``k``-th weekday counted from ``T0`` (0 = Monday T0)."""
    return (k // 5) * 7 + k % 5


# --------------------------------------------------------------------------
# Name analysis
# --------------------------------------------------------------------------

POS_WORDS = frozenset({
    "final", "best", "keep", "kept", "selected", "select", "chosen", "pick", "picked", "approved",
    "paper", "manuscript", "fig", "figure", "figures", "summary", "report", "results", "hits", "hit",
    "analysis", "curated", "clean", "medchem", "submitted", "submit", "top",
})
"""Words a human uses when naming kept or approved results."""

NEG_WORDS = frozenset({
    "old", "bak", "backup", "junk", "failed", "fail", "trash", "tmp", "temp", "scratch", "broken",
    "obsolete", "orig", "discard", "redo", "wrong",
})
"""Words marking discarded material; they taint a whole subtree."""

REPLICA_WORDS = frozenset({"rep", "replica", "lambda", "lam", "window", "win", "seed", "walker", "clone"})
"""Name tokens of a replica level (``rep3``, ``lambda_0.50``) nested inside one candidate."""

DERIVED_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".svg", ".pdf", ".xlsx", ".xls", ".csv", ".pptx", ".docx", ".ipynb",
    ".pse", ".vmd", ".tcl", ".txt", ".md",
})
"""Extensions of small human-made artifacts (plots, sheets, slides, notes)."""

MD_CLASSES: dict[str, frozenset[str]] = {
    "TOPO": frozenset({".prmtop", ".parm7", ".top", ".psf", ".gro", ".cms", ".tpr"}),
    "INPUT": frozenset({".in", ".mdp", ".inp", ".cfg", ".conf", ".namd", ".msj"}),
    "TRAJ": frozenset({".nc", ".dcd", ".xtc", ".trr", ".mdcrd"}),
    "RESTART": frozenset({".rst7", ".rst", ".ncrst", ".cpt", ".chk", ".xsc", ".coor", ".vel"}),
    "LOG": frozenset({".out", ".log", ".edr", ".mdout", ".err", ".ene"}),
}
"""MD file classes by extension; ``SCHED`` is matched by name (``SCHED_RE``)."""

SCHED_RE = re.compile(r"^slurm-\d+\.out$|\.[oe]\d+$")
"""Scheduler output names (Slurm, PBS/SGE ``job.o123``); checked before ``LOG``."""

MD_CLASS_NAMES: tuple[str, ...] = ("TOPO", "INPUT", "TRAJ", "RESTART", "LOG", "SCHED")
"""The six MD classes counted by coverage and signatures."""

ENGINE_EXTS: dict[str, frozenset[str]] = {
    "amber": frozenset({".prmtop", ".parm7", ".rst7", ".ncrst", ".nc", ".in"}),
    "gromacs": frozenset({".top", ".mdp", ".xtc", ".trr", ".cpt", ".edr", ".gro", ".tpr"}),
    "desmond": frozenset({".cms", ".cfg", ".msj", ".ene"}),
    "namd": frozenset({".psf", ".namd", ".inp", ".xsc", ".coor", ".dcd"}),
}
"""Extensions that vote for each MD engine."""

_CAMEL_RE = re.compile(r"([a-z])([A-Z])")
_SPLIT_RE = re.compile(r"[^a-z0-9]+")
_ALNUM_RE = re.compile(r"[a-z]+|\d+")
_ID_RE = re.compile(r"[a-z]+\d+")
_ID_SEP_RE = re.compile(r"([a-z]+)[_-]?(\d+)")
_VERSION_RE = re.compile(r"^v\d+$")
_TEMPLATED_RE = re.compile(r"^[a-z0-9_.\-]+$")
_DIGITS_RE = re.compile(r"\d+")
_MIB = 1 << 20
_BURST_GAP_S = 6 * 3600


def _raw_tokens(name: str) -> list[str]:
    snake = _CAMEL_RE.sub(r"\1_\2", name).lower()
    return [t for t in _SPLIT_RE.split(snake) if t]


def tokens(name: str) -> list[str]:
    """Split a name into lower-case word and number tokens.

    ``KDR_FEP_topHits_forMedChem.pptx`` -> ``kdr fep top hits for med chem pptx``;
    ``top10`` -> ``top 10``; ``lig017`` -> ``lig 017``.
    """
    out: list[str] = []
    for tok in _raw_tokens(name):
        out.extend(_ALNUM_RE.findall(tok))
    return out


def word_hits(name: str, words: Iterable[str]) -> set[str]:
    """Words of ``words`` present in ``name`` as a token or as two joined tokens.

    Joining adjacent tokens lets ``forMedChem`` hit ``medchem``.
    """
    toks = tokens(name)
    candidates = set(toks) | {a + b for a, b in zip(toks, toks[1:])}
    return candidates & set(words)


def has_version_marker(name: str) -> bool:
    """True if a raw token looks like ``v3`` (``dG_summary_v3.xlsx``)."""
    return any(_VERSION_RE.match(t) for t in _raw_tokens(name))


def template_key(name: str) -> str:
    """Lower-cased name with every digit run replaced by ``#``."""
    return _DIGITS_RE.sub("#", name.lower())


def is_templated(name: str) -> bool:
    """True for machine-style names: ``[a-z0-9_.-]`` only and at least one digit."""
    return bool(_TEMPLATED_RE.match(name)) and any(c.isdigit() for c in name)


def id_tokens(name: str) -> set[str]:
    """Candidate-id tokens of a name: ``letters[_-]?digits`` runs, joined, plus zero-stripped variants.

    ``lig017_rmsd.png`` -> ``{"lig017", "lig17"}``; ``cmpd_017_rmsd.png`` and
    ``lig-017.png`` give the same tokens as ``cmpd017``/``lig017``. The
    letters are always kept, so ``cmpd012`` never meets ``lig012``.
    """
    out: set[str] = set()
    for letters, digits in _ID_SEP_RE.findall(name.lower()):
        out.add(letters + digits)
        out.add(letters + str(int(digits)))
    return out


def id_token(name: str) -> str | None:
    """The longest ``[a-z]+\\d+`` run of the lower-cased name (first on ties)."""
    runs = _ID_RE.findall(name.lower())
    return max(runs, key=len) if runs else None


COMPRESSION_EXTS = frozenset({".gz", ".bz2", ".xz", ".zst"})
"""Compression suffixes stripped before classification (``complex.prmtop.gz`` is TOPO)."""


def is_trj_dir(name: str) -> bool:
    """True for a Desmond trajectory directory name (``<job>_trj``)."""
    return name.lower().endswith("_trj") and len(name) > 4


def is_trj_frame(name: str) -> bool:
    """True for a file Desmond writes inside ``<job>_trj/`` as the trajectory (``frame*``, ``clickme.dtr``)."""
    lower = name.lower()
    return lower.startswith("frame") or lower == "clickme.dtr"


def classify_name(name: str) -> str:
    """MD class of a file name: TOPO, INPUT, TRAJ, RESTART, LOG, SCHED, DERIVED or OTHER.

    A compression suffix (``.gz``, ``.bz2``, ``.xz``, ``.zst``) is stripped
    first, so ``complex.prmtop.gz`` is TOPO and ``poses.sdf.gz`` or
    ``pv.maegz`` are OTHER. A name with a directory part is classified by
    :func:`classify_path` rules (``md_trj/frame001`` is TRAJ).
    """
    if "/" in name:
        return classify_path(name)
    lower = name.lower()
    if SCHED_RE.search(lower):
        return "SCHED"
    stem, ext = posixpath.splitext(lower)
    if ext in COMPRESSION_EXTS:
        ext = posixpath.splitext(stem)[1]
    for cls, exts in MD_CLASSES.items():
        if ext in exts:
            return cls
    if ext in DERIVED_EXTS:
        return "DERIVED"
    return "OTHER"


def classify_path(path: str) -> str:
    """MD class of a file path: a trajectory frame inside a Desmond ``<job>_trj/`` directory is TRAJ,
    anything else is classified by its name (:func:`classify_name`)."""
    parent, name = posixpath.split(path)
    if is_trj_dir(posixpath.basename(parent)) and is_trj_frame(name):
        return "TRAJ"
    return classify_name(name)


def classify(entry: Entry) -> str:
    """MD class of a file entry (see :func:`classify_path`)."""
    return classify_path(entry.path)


def engine_vote(files: Iterable[Entry]) -> str:
    """MD engine voted by the distinct extensions of ``files``, else ``"unknown"``.

    Each distinct extension votes once for every engine listing it; ties go
    to the engine listed first in ``ENGINE_EXTS``.
    """
    exts = {f.ext for f in files}
    votes = {eng: len(exts & eng_exts) for eng, eng_exts in ENGINE_EXTS.items()}
    best = max(votes.values())
    if best == 0:
        return "unknown"
    return next(eng for eng, n in votes.items() if n == best)


def chunk_index(entry: Entry) -> int | None:
    """Numeric index of a trajectory chunk: the last digit run of its stem."""
    runs = _DIGITS_RE.findall(entry.stem)
    return int(runs[-1]) if runs else None


def files_within(inv: Inventory, path: str, max_depth: int = 2) -> list[Entry]:
    """Regular files at depth 1..``max_depth`` below ``path`` (symlinks not followed).

    A Desmond ``<job>_trj`` directory is part of the level that holds it:
    its files count at that level's depth, so a trajectory folds into its run.
    """
    out: list[Entry] = []
    level = [path]
    for _ in range(max_depth):
        nxt: list[str] = []
        while level:
            d = level.pop()
            for c in inv.children(d):
                if c.kind == "f":
                    out.append(c)
                elif c.kind == "d" and is_trj_dir(c.name):
                    level.append(c.path)
                elif c.kind == "d":
                    nxt.append(c.path)
        level = nxt
    return sorted(out, key=lambda e: e.path)


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """Jaccard similarity of two collections as sets (0.0 when both are empty)."""
    sa, sb = set(a), set(b)
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def chunk_regularity(chunks: list[Entry]) -> float | None:
    """``1 - pstdev/mean`` of consecutive mtime intervals, clamped to [0, 1].

    ``chunks`` must be sorted by index; ``None`` with fewer than 3 chunks.
    """
    if len(chunks) < 3:
        return None
    intervals = [b.mtime - a.mtime for a, b in zip(chunks, chunks[1:])]
    mean = statistics.fmean(intervals)
    if mean <= 0:
        return 0.0
    return min(1.0, max(0.0, 1.0 - statistics.pstdev(intervals) / mean))


# --------------------------------------------------------------------------
# Per-directory features
# --------------------------------------------------------------------------


@dataclass
class DirFeatures:
    """Shape features of one directory.

    "Files" are the direct child regular files unless a field says otherwise;
    ``md_class_coverage``, ``engine``, ``signature`` and the ``traj_*`` fields
    look at files up to depth 2 so ``rep*``/``lambda_*`` sublevels fold in.
    Time fractions partition the files: working hours + weekday off-hours +
    weekend = 1.
    """

    path: str
    depth: int
    n_files: int
    n_dirs: int
    n_links: int
    total_bytes: int
    name_is_templated: bool
    name_template: str
    pos_word_score: int
    neg_word_score: int
    has_version_marker: bool
    class_counts: dict[str, int]
    md_class_coverage: int
    engine: str
    signature: tuple[str, ...]
    traj_byte_fraction: float
    traj_chunk_count: int
    traj_chunk_regularity: float | None
    traj_series_gap: bool
    derived_fraction: float
    small_file_fraction: float
    median_file_size: float
    uid_set: frozenset[int]
    dominant_uid: int | None
    uid_purity: float
    working_hours_fraction: float
    offhours_fraction: float
    weekend_fraction: float
    mtime_min: int | None
    mtime_max: int | None
    n_bursts: int
    burst_ratio: float
    child_name_diversity: float


def dominant(values: Iterable[int]) -> tuple[int | None, float]:
    """Most common value (smallest on ties) and its share; ``(None, 0.0)`` if empty."""
    values = list(values)
    if not values:
        return None, 0.0
    counts = Counter(values)
    top = max(counts.values())
    uid = min(v for v, n in counts.items() if n == top)
    return uid, top / len(values)


def _chunk_series(trajs: list[Entry]) -> list[list[Entry]]:
    series: dict[tuple[str | None, str], list[Entry]] = {}
    for t in trajs:
        if chunk_index(t) is not None:
            series.setdefault((t.parent, template_key(t.name)), []).append(t)
    return [sorted(s, key=lambda e: (chunk_index(e), e.name)) for _, s in sorted(series.items())]


def _has_gap(series: list[Entry]) -> bool:
    idx = {chunk_index(e) for e in series}
    return max(idx) - min(idx) + 1 != len(idx)  # type: ignore[type-var, operator]


def count_bursts(mtimes: Iterable[int], gap_s: int = _BURST_GAP_S) -> int:
    """Number of activity bursts: sorted mtimes split at gaps larger than ``gap_s``."""
    ts = sorted(mtimes)
    if not ts:
        return 0
    return 1 + sum(1 for a, b in zip(ts, ts[1:]) if b - a > gap_s)


def dir_features(inv: Inventory, path: str, *, tz_offset_s: int = TZ_OFFSET_S) -> DirFeatures:
    """Compute :class:`DirFeatures` for the directory at ``path``."""
    entry = inv.by_path[path]
    kids = inv.children(path)
    files = [c for c in kids if c.kind == "f"]
    n_dirs = sum(1 for c in kids if c.kind == "d")
    n_links = sum(1 for c in kids if c.kind == "l")
    deep = files_within(inv, path, 2)
    deep_cls = [(f, classify(f)) for f in deep]
    md_deep = [(f, c) for f, c in deep_cls if c in MD_CLASS_NAMES]
    deep_bytes = sum(f.size for f in deep)
    trajs = [f for f, c in md_deep if c == "TRAJ"]
    series = _chunk_series(trajs)
    regs = [r for r in (chunk_regularity(s) for s in series) if r is not None]
    classes = [classify(f) for f in files]
    sizes = [f.size for f in files]
    mtimes = [f.mtime for f in files]
    n = len(files)
    dominant_uid, uid_purity = dominant(f.uid for f in files)
    wh = sum(1 for t in mtimes if is_working_hours(t, tz_offset_s))
    we = sum(1 for t in mtimes if weekday(t, tz_offset_s) >= 5)
    named = [c for c in kids if c.kind in ("f", "d")]
    bursts = count_bursts(mtimes)
    name = entry.name
    return DirFeatures(
        path=path,
        depth=0 if path == "/" else path.count("/"),
        n_files=n,
        n_dirs=n_dirs,
        n_links=n_links,
        total_bytes=sum(sizes),
        name_is_templated=is_templated(name),
        name_template=template_key(name),
        pos_word_score=len(word_hits(name, POS_WORDS)),
        neg_word_score=len(word_hits(name, NEG_WORDS)),
        has_version_marker=has_version_marker(name),
        class_counts=dict(sorted(Counter(classes).items())),
        md_class_coverage=len({c for _, c in md_deep}),
        engine=engine_vote(f for f, _ in md_deep),
        signature=tuple(sorted({f"{c}:{template_key(f.name)}" for f, c in md_deep})),
        traj_byte_fraction=sum(t.size for t in trajs) / deep_bytes if deep_bytes else 0.0,
        traj_chunk_count=sum(len(s) for s in series),
        traj_chunk_regularity=statistics.fmean(regs) if regs else None,
        traj_series_gap=any(_has_gap(s) for s in series),
        derived_fraction=classes.count("DERIVED") / n if n else 0.0,
        small_file_fraction=sum(1 for s in sizes if s < _MIB) / n if n else 0.0,
        median_file_size=float(statistics.median(sizes)) if sizes else 0.0,
        uid_set=frozenset(f.uid for f in files),
        dominant_uid=dominant_uid,
        uid_purity=uid_purity,
        working_hours_fraction=wh / n if n else 0.0,
        offhours_fraction=(n - wh - we) / n if n else 0.0,
        weekend_fraction=we / n if n else 0.0,
        mtime_min=min(mtimes) if mtimes else None,
        mtime_max=max(mtimes) if mtimes else None,
        n_bursts=bursts,
        burst_ratio=bursts / n if n else 0.0,
        child_name_diversity=len({template_key(c.name) for c in named}) / len(named) if named else 0.0,
    )


def all_features(inv: Inventory, *, tz_offset_s: int = TZ_OFFSET_S) -> dict[str, DirFeatures]:
    """:class:`DirFeatures` for every directory, keyed by path."""
    return {d.path: dir_features(inv, d.path, tz_offset_s=tz_offset_s) for d in inv.dirs()}


def sibling_uniformity(
    inv: Inventory, feats: dict[str, DirFeatures], parent_path: str
) -> tuple[list[str], float, float, tuple[str, ...]]:
    """How machine-made the child directories of ``parent_path`` look.

    Child dirs are grouped by ``name_template``; the largest group ``G`` wins
    (ties: lexicographically smallest template). Returns ``(G paths sorted,
    uniformity, template_fraction, mode_sig)`` where ``mode_sig`` is the most
    common signature in ``G`` (ties: smallest), ``uniformity`` the mean Jaccard
    of each member's signature with ``mode_sig`` and ``template_fraction`` =
    ``|G|`` / number of child dirs. Without child dirs: ``([], 0.0, 0.0, ())``.
    """
    child_dirs = [c.path for c in inv.children(parent_path) if c.kind == "d"]
    if not child_dirs:
        return [], 0.0, 0.0, ()
    groups: dict[str, list[str]] = {}
    for p in child_dirs:
        groups.setdefault(feats[p].name_template, []).append(p)
    template = min(groups, key=lambda t: (-len(groups[t]), t))
    group = sorted(groups[template])
    sig_counts = Counter(feats[p].signature for p in group)
    top = max(sig_counts.values())
    mode_sig = min(s for s, k in sig_counts.items() if k == top)
    uniformity = statistics.fmean(jaccard(feats[p].signature, mode_sig) for p in group)
    return group, uniformity, len(group) / len(child_dirs), mode_sig
