"""Campaign detector: find MD campaigns, curated dirs and the picked candidates.

The pipeline (see README.md) is: featurize every directory, find campaign
roots from sibling uniformity, taint discarded subtrees, score curated
directories, collect link evidence from curated dirs to candidates, drop
evidence that covers (nearly) all candidates, then label candidates.
"""

from __future__ import annotations

import functools
import posixpath
import re
import statistics
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .features import (
    DERIVED_EXTS, MD_CLASS_NAMES, NEG_WORDS, POS_WORDS, REPLICA_WORDS, DirFeatures, all_features, classify,
    dominant, era, files_within, has_version_marker, id_tokens, is_working_hours, sibling_uniformity, tokens,
    word_hits,
)
from .inventory import Entry, Inventory, normalize_path

EVIDENCE_KINDS: tuple[str, ...] = ("copy_out", "hardlink", "symlink", "derived", "text_mention", "graduation")
"""Kinds of selection evidence."""

EVIDENCE_WEIGHTS: dict[str, float] = {
    "copy_out": 1.0, "hardlink": 1.0, "symlink": 1.0, "derived": 0.7, "graduation": 0.5,
}
"""Weights of the built-in evidence kinds (hooks choose their own weights)."""


@dataclass
class Params:
    """Detector thresholds. Defaults are the documented operating point."""

    min_candidates: int = 4
    template_fraction: float = 0.6
    uniformity: float = 0.75
    min_md_classes: int = 3
    traj_byte_fraction: float = 0.5
    uid_purity: float = 0.9
    chunk_regularity: float = 0.6
    campaign_conf: float = 0.6
    curated_score: int = 3
    coverage_cap: float = 0.8
    pick_threshold: float = 0.7
    selection_conf: float = 0.3
    tz_offset_s: int = 0
    copy_overlap: float = 0.8
    require_topology: bool = True
    """A campaign needs a TOPO file in its members' modal signature or directly in the root."""
    min_run_span_s: int = 3600
    """Median member run window (first MD file -> last trajectory chunk) a campaign needs: compute happened."""
    batch_subsets: bool = True
    """Also evaluate same-signature batches of every template group, not only the largest group."""
    batch_max_gap_s: int = 7 * 86400
    """Largest idle gap between the run windows of a batch (one submission, overlapping or back-to-back)."""
    drop_replica_roots: bool = True
    """Drop a replica-level root (``rep#``, ``lambda_#``) that no outer campaign absorbs."""
    mirror_provenance: bool = True
    """Mirror gate: taint and provenance (submit script, analysis dir) outrank ctime."""
    derived_locality: bool = True
    """Derived evidence counts only from a curated dir local to the campaign or holding link evidence into it."""
    derived_uniqueness: bool = True
    """A derived-extension file whose hash occurs in >= 2 candidates is boilerplate, not derived evidence."""
    symlink_max_hops: int = 40
    """Symlink chains are followed up to this many hops (loops stop earlier)."""
    script_cadence: bool = True
    """A submitter-owned dir written like a script (onset, density or offset lock) is never curated."""
    script_onset_s: int = 3600
    """Onset lock: a submitter-owned dir first written within this long after the last chunk is the job's."""
    script_density_s: int = 10
    """Density/offset lock tolerance: one entry per this many seconds, or offsets equal within it."""


@dataclass
class Evidence:
    """One link from a human-touched path (``src``) to a candidate (``ref``)."""

    kind: str
    candidate: str
    src: str
    ref: str
    weight: float
    note: str = ""


@dataclass
class Candidate:
    """One candidate (a member directory of the campaign) and its label."""

    id: str
    path: str
    label: str
    score: float
    evidence: list[Evidence]
    features: DirFeatures


@dataclass
class CuratedDir:
    """A directory that looks human-curated relative to one campaign.

    ``n_files`` counts its direct files and symlinks; ``reasons`` lists the
    criteria it met (``score`` of them).
    """

    path: str
    uid: int | None
    score: int
    n_files: int
    reasons: list[str]


@dataclass
class CampaignReport:
    """Everything detected about one campaign root."""

    root: str
    engine: str
    era: int
    template: str
    n_candidates: int
    uniformity: float
    submitter_uid: int | None
    t_start: int
    t_end: int
    confidence: float
    curated_dirs: list[CuratedDir]
    candidates: list[Candidate]
    missing_ids: list[str]
    selection_confidence: float
    notes: list[str]

    def _with(self, label: str) -> set[str]:
        return {c.id for c in self.candidates if c.label == label}

    def picked(self) -> set[str]:
        """Ids of candidates labelled ``picked``."""
        return self._with("picked")

    def not_picked(self) -> set[str]:
        """Ids of candidates labelled ``not_picked``."""
        return self._with("not_picked")

    def unknown(self) -> set[str]:
        """Ids of candidates labelled ``unknown``."""
        return self._with("unknown")


_FEATURE_SUMMARY = ("n_files", "traj_chunk_count", "traj_chunk_regularity", "traj_byte_fraction",
                    "md_class_coverage", "engine", "dominant_uid", "mtime_min", "mtime_max")


@dataclass
class DetectionResult:
    """Detector output: one report per campaign root, sorted by root."""

    campaigns: list[CampaignReport]

    @property
    def campaign_roots(self) -> list[str]:
        """Detected campaign root paths."""
        return [c.root for c in self.campaigns]

    def to_dict(self) -> dict[str, object]:
        """JSON-serialisable form; candidate features are summarised."""
        out = []
        for rep in self.campaigns:
            d = {k: v for k, v in vars(rep).items() if k not in ("curated_dirs", "candidates")}
            d["curated_dirs"] = [vars(c) for c in rep.curated_dirs]
            d["candidates"] = [
                {"id": c.id, "path": c.path, "label": c.label, "score": c.score,
                 "evidence": [vars(e) for e in c.evidence],
                 "features": {k: getattr(c.features, k) for k in _FEATURE_SUMMARY}}
                for c in rep.candidates
            ]
            out.append(d)
        return {"campaigns": out}


EvidenceHook = Callable[[Inventory, CampaignReport], Iterable[Evidence]]
"""Signature of a hook: returns extra evidence for one campaign."""


def no_evidence(inv: Inventory, report: CampaignReport) -> Iterable[Evidence]:
    """Default hook: contributes nothing."""
    return ()


@dataclass
class Hooks:
    """Extension points called once per campaign after built-in evidence.

    Each hook sees the report with candidates, curated dirs, times and
    ``submitter_uid`` filled in (labels not yet assigned) and returns
    :class:`Evidence` whose ``candidate`` is a candidate id of that report.
    """

    text_mentions: EvidenceHook = no_evidence
    graduation: EvidenceHook = no_evidence


def is_within(path: str, ancestor: str) -> bool:
    """True if ``path`` equals ``ancestor`` or lies below it."""
    return ancestor == "/" or path == ancestor or path.startswith(ancestor + "/")


def is_tainted(path: str, anchor: str = "/") -> bool:
    """True if a component of ``path`` below its common ancestor with ``anchor``
    carries a ``NEG_WORDS`` token (old, bak, trash...).

    The detector anchors at the campaign root, so an archive that lives under
    ``/scratch`` is not tainted as a whole while ``analysis/old`` still is.
    """
    common = posixpath.commonpath([path, anchor])
    return any(word_hits(part, NEG_WORDS) for part in path[len(common):].split("/") if part)


def _name_signal(name: str) -> bool:
    return bool(word_hits(name, POS_WORDS)) or has_version_marker(name)


# --------------------------------------------------------------------------
# Step 2: campaign roots
# --------------------------------------------------------------------------


@dataclass
class _Root:
    path: str
    group: list[str]
    uniformity: float
    template: str
    engine: str
    confidence: float
    submitter_uid: int | None
    t_start: int
    t_end: int
    notes: list[str]
    traj_shas: frozenset[str]
    first_ctime: int
    run_span_s: float
    run_ends: dict[str, int]


_SCRIPT_EXTS = frozenset({".sh", ".bash", ".csh", ".zsh", ".slurm", ".sbatch", ".pbs", ".job", ".fmp", ".msj"})
"""Extensions of submission scripts and workflow files a campaign root keeps beside its runs."""


def _run_window(inv: Inventory, member: str) -> tuple[int, int] | None:
    """``(first MD-file mtime, last trajectory mtime)`` of one member (depth <= 2), ``None`` without TRAJ."""
    md = [(f, classify(f)) for f in files_within(inv, member, 2)]
    md = [(f, c) for f, c in md if c in MD_CLASS_NAMES]
    trajs = [f.mtime for f, c in md if c == "TRAJ"]
    if not trajs:
        return None
    return min(f.mtime for f, _ in md), max(trajs)


def _cotemporal(windows: list[tuple[int, int]], max_gap_s: int) -> bool:
    """True when the run windows, sorted by start, never leave a gap longer than ``max_gap_s``."""
    ordered = sorted(windows)
    end = ordered[0][1]
    for start, stop in ordered[1:]:
        if start - end > max_gap_s:
            return False
        end = max(end, stop)
    return True


def _evaluate_group(inv: Inventory, feats: dict[str, DirFeatures], path: str, group: list[str], uniformity: float,
                    tfrac: float, mode_sig: tuple[str, ...], p: Params, *, batch: bool) -> _Root | str:
    """Apply the campaign-root gates to ``group`` (child dirs of ``path``); a gate name on rejection.

    ``batch=True`` evaluates a same-signature subset of a template group
    (:func:`_batches`): the template-fraction gate is replaced by the batch
    definition (one submitter, run windows that overlap or follow each other).
    """
    classes = {s.split(":", 1)[0] for s in mode_sig}
    if len(group) < p.min_candidates:
        return "min_candidates"
    if not batch and tfrac < p.template_fraction:
        return "template_fraction"
    if uniformity < p.uniformity:
        return "uniformity"
    if len(classes) < p.min_md_classes:
        return "min_md_classes"
    if "TRAJ" not in classes:
        return "no_traj"
    files = [f for m in group for f in files_within(inv, m, 2)]
    total = sum(f.size for f in files)
    trajs = [f for f in files if classify(f) == "TRAJ"]
    traj_frac = sum(f.size for f in trajs) / total if total else 0.0
    submitter, purity = dominant(f.uid for f in files)
    if traj_frac < p.traj_byte_fraction:
        return "traj_byte_fraction"
    if purity < p.uid_purity:
        return "uid_purity"
    if p.require_topology and "TOPO" not in classes and not any(
            c.kind == "f" and classify(c) == "TOPO" for c in inv.children(path)):
        return "no_topology"
    by_member = {m: _run_window(inv, m) for m in group}
    windows = [w for w in by_member.values() if w is not None]
    if batch and not _cotemporal(windows, p.batch_max_gap_s):
        return "batch_not_cotemporal"
    regs = [feats[m].traj_chunk_regularity for m in group if feats[m].traj_chunk_regularity is not None]
    reg = statistics.fmean(regs) if regs else 0.0
    md_classes = len(classes & set(MD_CLASS_NAMES))
    confidence = 0.3 * uniformity + 0.2 * md_classes / 6 + 0.2 * traj_frac + 0.15 * reg + 0.15 * purity
    if confidence < p.campaign_conf:
        return "campaign_conf"
    notes = []
    if batch:
        notes.append(f"batch of {len(group)} same-signature, one-submitter runs among the child dirs of {path}")
    if reg < p.chunk_regularity:
        notes.append(f"irregular chunk mtimes (regularity {reg:.2f} < {p.chunk_regularity}): "
                     "chunks may have been copied or touched after the run")
    gaps = sum(1 for m in group if feats[m].traj_series_gap)
    if gaps:
        notes.append(f"{gaps} candidates have gaps in their trajectory chunk series (incomplete runs)")
    engines = Counter(feats[m].engine for m in group)
    return _Root(
        path=path, group=group, uniformity=uniformity, template=feats[group[0]].name_template,
        engine=min(engines, key=lambda e: (-engines[e], e)), confidence=confidence, submitter_uid=submitter,
        t_start=min(f.mtime for f in trajs), t_end=max(f.mtime for f in trajs), notes=notes,
        traj_shas=frozenset(f.sha256 for f in trajs if f.sha256), first_ctime=min(f.ctime for f in trajs),
        run_span_s=statistics.median(stop - start for start, stop in windows),
        run_ends={m: w[1] for m, w in by_member.items() if w is not None},
    )


def _batches(inv: Inventory, feats: dict[str, DirFeatures], path: str,
             p: Params) -> Iterable[tuple[list[str], float, tuple[str, ...]]]:
    """Same-signature subsets of every template group of ``path``'s child dirs, largest group first.

    Within a template group, the members whose MD signature holds TRAJ are
    grouped by exact signature; the most common signature (ties: smallest)
    is the batch. Yields ``(members, uniformity 1.0, signature)``.
    """
    groups: dict[str, list[str]] = {}
    for c in inv.children(path):
        if c.kind == "d":
            groups.setdefault(feats[c.path].name_template, []).append(c.path)
    for template in sorted(groups, key=lambda t: (-len(groups[t]), t)):
        by_sig: dict[tuple[str, ...], list[str]] = {}
        for m in groups[template]:
            sig = feats[m].signature
            if any(s.startswith("TRAJ:") for s in sig):
                by_sig.setdefault(sig, []).append(m)
        if by_sig:
            sig = min(by_sig, key=lambda s: (-len(by_sig[s]), s))
            if len(by_sig[sig]) >= p.min_candidates:
                yield sorted(by_sig[sig]), 1.0, sig


def _evaluate_root(inv: Inventory, feats: dict[str, DirFeatures], path: str, p: Params) -> _Root | str:
    """Evaluate ``path`` as a campaign root; the name of the first failed gate on rejection.

    The largest template group of the child dirs is tried first
    (:func:`~campaign_detector.features.sibling_uniformity`). If it fails,
    every same-signature batch of every template group is tried
    (:func:`_batches`), so a uniform subset inside a heterogeneous group or
    an outnumbered template group can still be a campaign.
    """
    if feats[path].n_dirs < p.min_candidates:
        return "min_candidates"
    group, uniformity, tfrac, mode_sig = sibling_uniformity(inv, feats, path)
    first = _evaluate_group(inv, feats, path, group, uniformity, tfrac, mode_sig, p, batch=False)
    if isinstance(first, _Root) or not p.batch_subsets:
        return first
    batch_gates = []
    for members, uni, sig in _batches(inv, feats, path, p):
        if members == group:
            continue
        found = _evaluate_group(inv, feats, path, members, uni, 1.0, sig, p, batch=True)
        if isinstance(found, _Root):
            return found
        batch_gates.append(found)
    return first + "".join(f"|batch:{g}" for g in batch_gates)


def _is_replica_level(template: str) -> bool:
    return bool(set(tokens(template)) & REPLICA_WORDS)


def _find_roots(inv: Inventory, feats: dict[str, DirFeatures], p: Params,
                verdicts: dict[str, str] | None = None) -> list[_Root]:
    """Qualifying roots, deepest first; an outer root absorbs roots inside its members.

    Exception: when at least half of the members hold an inner root whose
    members are not a replica level (``rep#``, ``lambda_#.#``...), the
    members are campaigns in their own right (``batch1..batch4``) and the
    outer directory is not a root. A replica-level root that no outer root
    absorbs is dropped: replicas are repeats of one candidate, never
    candidates. ``verdicts`` (if given) receives a gate name or ``"root"``
    for every directory with at least ``min_candidates`` child dirs.
    """
    found: dict[str, _Root] = {}
    verdict: dict[str, str] = {}
    for d in sorted(inv.dirs(), key=lambda e: (-feats[e.path].depth, e.path)):
        root = _evaluate_root(inv, feats, d.path, p)
        if isinstance(root, str):
            if feats[d.path].n_dirs >= p.min_candidates:
                verdict[d.path] = root
            continue
        inner = [r for r in found.values() if any(is_within(r.path, m) for m in root.group)]
        campaigns = {m for m in root.group for r in inner
                     if is_within(r.path, m) and not _is_replica_level(r.template)}
        if 2 * len(campaigns) >= len(root.group):
            verdict[d.path] = "members_are_campaigns"
            continue
        for r in inner:
            del found[r.path]
            verdict[r.path] = f"absorbed_by:{d.path}"
        found[d.path] = root
        verdict[d.path] = "root"
    out = []
    for path in sorted(found):
        if p.drop_replica_roots and _is_replica_level(found[path].template):
            verdict[path] = "replica_level"
        else:
            out.append(found[path])
    if verdicts is not None:
        verdicts.update(verdict)
    return out


def _provenance(inv: Inventory, root: _Root) -> int:
    """Signs that ``root`` is where the campaign was run: a submit script beside the runs (1) and a
    non-member directory such as ``analysis/`` inside the root (1)."""
    members = set(root.group)
    kids = inv.children(root.path)
    script = any(c.kind == "f" and (c.ext in _SCRIPT_EXTS or word_hits(c.stem, {"submit"})) for c in kids)
    side_dir = any(c.kind == "d" and c.path not in members for c in kids)
    return int(script) + int(side_dir)


def _split_copies(inv: Inventory, roots: list[_Root], p: Params) -> tuple[list[_Root], list[_Root]]:
    """Separate campaigns from byte-identical copies of other campaigns.

    ``r`` is a copy of ``other`` when at least ``copy_overlap`` of ``r``'s
    trajectory hashes occur in ``other`` and ``other`` ranks first by, in
    order: not tainted relative to the other root (``backup/``, ``old/``),
    more provenance (:func:`_provenance`: a submit script, an analysis dir),
    earlier chunk ctime. The original gets a note. Provenance before ctime
    matters when a working copy was restored from its own mirror.
    """
    def rank(r: _Root, other: _Root) -> tuple[bool, int, int]:
        provenance = _provenance(inv, r) if p.mirror_provenance else 0
        return is_tainted(r.path, anchor=other.path), -provenance, r.first_ctime

    copies: list[_Root] = []
    for r in roots:
        for other in roots:
            if other is r or not r.traj_shas or other in copies:
                continue
            overlap = len(r.traj_shas & other.traj_shas) / len(r.traj_shas)
            if overlap >= p.copy_overlap and rank(other, r) < rank(r, other):
                copies.append(r)
                other.notes.append(f"ignored {r.path}: {overlap:.0%} of its trajectory chunks are copies of this "
                                   "campaign's (mirror/backup)")
                break
    return [r for r in roots if r not in copies], copies


def _campaign_roots(inv: Inventory, feats: dict[str, DirFeatures], p: Params,
                    verdicts: dict[str, str] | None = None) -> tuple[list[_Root], list[_Root]]:
    """Step 2: ``(campaign roots, mirror/backup copies)``.

    Roots come from :func:`_find_roots`, copies are split off by
    :func:`_split_copies`, then roots where no computation happened are
    dropped (compute-happened gate): the median member run window (first MD
    file to last trajectory chunk) is below ``min_run_span_s``, as in a bulk
    copy of course kits (every file carries the copy instant) or a screen
    that crashed minutes into its first chunk. Copies are split first so a
    mirror whose chunk mtimes were not preserved is still recognised.
    """
    v: dict[str, str] = {}
    roots, copies = _split_copies(inv, _find_roots(inv, feats, p, v), p)
    for c in copies:
        v[c.path] = "mirror_copy"
    kept = []
    for r in roots:
        if r.run_span_s < p.min_run_span_s:
            v[r.path] = "no_compute"
        else:
            kept.append(r)
    if verdicts is not None:
        verdicts.update(v)
    return kept, copies


def root_verdicts(inv: Inventory, *, params: Params | None = None) -> dict[str, str]:
    """Why each would-be root is or is not a campaign: path -> ``"root"`` or the gate that rejected it.

    Covers every directory with at least ``min_candidates`` child dirs.
    Gate names: ``template_fraction``, ``uniformity``, ``min_md_classes``,
    ``no_traj``, ``no_topology``, ``traj_byte_fraction``, ``uid_purity``,
    ``campaign_conf``, ``min_candidates`` (template group too small),
    ``members_are_campaigns``, ``absorbed_by:<outer root>``,
    ``replica_level``, ``mirror_copy``, ``no_compute``. When the largest
    template group fails and same-signature batches were tried too, their
    gates follow as ``|batch:<gate>`` (``uniformity|batch:uid_purity``).
    """
    p = params or Params()
    feats = all_features(inv, tz_offset_s=p.tz_offset_s)
    out: dict[str, str] = {}
    _campaign_roots(inv, feats, p, out)
    return dict(sorted(out.items()))


def _missing_ids(names: list[str]) -> list[str]:
    """Ids absent from the numeric range of the last digit run of ``names``."""
    runs = [(n, list(re.finditer(r"\d+", n))) for n in names]
    if not runs or any(not r for _, r in runs):
        return []
    shapes = {(n[:r[-1].start()], n[r[-1].end():]) for n, r in runs}
    widths = {len(r[-1].group()) for _, r in runs}
    if len(shapes) != 1:
        return []
    prefix, suffix = shapes.pop()
    values = {int(r[-1].group()) for _, r in runs}
    lo, hi = min(values), max(values)
    if hi - lo + 1 > 10 * len(values):
        return []
    width = widths.pop() if len(widths) == 1 else 0
    return [f"{prefix}{str(i).zfill(width)}{suffix}" for i in range(lo, hi + 1) if i not in values]


# --------------------------------------------------------------------------
# Steps 3-7: curation, evidence, coverage cap, labels
# --------------------------------------------------------------------------


def _owner(path: str, dirs: dict[str, str]) -> str | None:
    """Value of the nearest ancestor-or-self of ``path`` found in ``dirs`` (path -> id)."""
    p = path
    while p != "/":
        if p in dirs:
            return dirs[p]
        p = posixpath.dirname(p)
    return None


class _Context:
    """Lookups shared by all campaigns of one inventory."""

    def __init__(self, inv: Inventory, feats: dict[str, DirFeatures], roots: list[_Root],
                 copies: list[_Root]) -> None:
        self.inv = inv
        self.feats = feats
        every = roots + copies
        self.all_candidates = {m: posixpath.basename(m) for r in every for m in r.group}
        self.outside_roots = [d for d in inv.dirs() if not any(is_within(d.path, r.path) for r in every)]

    def inside_any_candidate(self, path: str) -> bool:
        return _owner(path, self.all_candidates) is not None


def _script_shaped(entries: list[Entry], root: _Root, p: Params) -> str | None:
    """Why a directory written under the submitter's uid looks like the job's own output, else ``None``.

    Signals (any one suffices): onset lock (first write no later than
    ``script_onset_s`` after the campaign's last chunk, or before it), write
    density (every entry written within ``script_density_s`` per entry),
    and per-candidate offset lock (id-named files of >= 3 candidates land at
    the same offset, within ``script_density_s``, from each candidate's own
    last chunk). A person working in the same account arrives later and
    writes by hand. Hard links are ignored: their mtime and uid belong to
    the linked inode, not to the act of linking.
    """
    entries = [e for e in entries if e.kind == "l" or e.nlink == 1]
    if not entries:
        return None
    mtimes = sorted(e.mtime for e in entries)
    if mtimes[0] <= root.t_end + p.script_onset_s:
        return f"first write {mtimes[0] - root.t_end:+d} s from the campaign's last chunk"
    if len(mtimes) >= 3 and mtimes[-1] - mtimes[0] <= p.script_density_s * (len(mtimes) - 1):
        return f"{len(mtimes)} entries written within {mtimes[-1] - mtimes[0]} s"
    ends = {posixpath.basename(m): t for m, t in root.run_ends.items()}
    by_token = {tok: cid for cid in ends for tok in id_tokens(cid)}
    offsets: dict[str, int] = {}
    for e in entries:
        named = {by_token[t] for t in id_tokens(e.name) if t in by_token}
        if len(named) == 1:
            cid = named.pop()
            offsets[cid] = min(offsets.get(cid, e.mtime - ends[cid]), e.mtime - ends[cid])
    if len(offsets) >= 3 and max(offsets.values()) - min(offsets.values()) <= p.script_density_s:
        return f"id-named files sit {min(offsets.values())} s after their own run's last chunk"
    return None


def _curated_dirs(ctx: _Context, root: _Root, p: Params, tainted: Callable[[str], bool],
                  notes: list[str] | None = None) -> list[CuratedDir]:
    """Score untainted non-candidate dirs; files and symlinks both count as entries.

    With ``script_cadence``, a directory owned by the submitter that is
    script-shaped (:func:`_script_shaped`) is never curated; ``notes``
    receives why.
    """
    root_parent = posixpath.dirname(root.path)
    out = []
    for path, f in ctx.feats.items():
        entries = [c for c in ctx.inv.children(path) if c.kind in ("f", "l")]
        if len(entries) < 2 or tainted(path) or ctx.inside_any_candidate(path):
            continue
        if is_within(path, root_parent) and path != root_parent:
            names = path[len(root_parent):].strip("/").split("/")
            if is_within(path, root.path):
                names = names[1:]
        else:
            names = [posixpath.basename(path)]
        mtimes = [c.mtime for c in entries]
        working = sum(1 for t in mtimes if is_working_hours(t, p.tz_offset_s)) / len(entries)
        owner, _ = dominant(c.uid for c in entries)
        reasons = []
        if any(_name_signal(n) for n in names):
            reasons.append("approval word or version marker in name")
        if f.derived_fraction >= 0.5:
            reasons.append(f"derived files {f.derived_fraction:.0%}")
        if working >= 0.6:
            reasons.append(f"working hours {working:.0%}")
        if min(mtimes) > root.t_end:
            reasons.append("written after the campaign")
        if owner != root.submitter_uid:
            reasons.append(f"owner uid {owner} is not the submitter")
        if not f.name_is_templated and f.child_name_diversity >= 0.5:
            reasons.append("irregular hand-made names")
        if len(reasons) < p.curated_score:
            continue
        script = _script_shaped(entries, root, p) if p.script_cadence and owner == root.submitter_uid else None
        if script is not None:
            if notes is not None:
                notes.append(f"{path} is not curated: written by the submitter like a script ({script})")
            continue
        out.append(CuratedDir(path=path, uid=owner, score=len(reasons), n_files=len(entries), reasons=reasons))
    return out


def _unique_owner(matches: Iterable[Entry], cands: dict[str, str]) -> tuple[str, str] | None:
    """``(candidate id, first matching path)`` if ``matches`` fall under exactly one candidate."""
    owners: dict[str, str] = {}
    for m in matches:
        cid = _owner(m.path, cands)
        if cid is not None:
            owners.setdefault(cid, m.path)
    return next(iter(owners.items())) if len(owners) == 1 else None


def _volume(path: str) -> str:
    """First path component: the inventory has no device column, so this stands for the volume."""
    return path.split("/", 2)[1] if path != "/" else ""


def _is_local(path: str, root: _Root) -> bool:
    """True when ``path`` is on the campaign's volume and within the root's parent (locality rule)."""
    return _volume(path) == _volume(root.path) and is_within(path, posixpath.dirname(root.path))


def _follow_symlink(inv: Inventory, link: Entry, cands: dict[str, str], max_hops: int) -> tuple[str, str] | None:
    """``(candidate id, target path)`` for the first path along ``link``'s chain inside a candidate.

    Each hop resolves the stored target against the link's directory; the
    walk continues while the target is itself a symlink in the inventory, up
    to ``max_hops`` hops, and gives up on a loop. A dangling or foreign end
    yields ``None``.
    """
    seen = {link.path}
    cur = link
    for _ in range(max_hops):
        tgt = cur.resolved_target()
        if tgt is None:
            return None
        cid = _owner(tgt, cands)
        if cid is not None:
            return cid, tgt
        nxt = inv.by_path.get(tgt)
        if nxt is None or nxt.kind != "l" or nxt.path in seen:
            return None
        seen.add(nxt.path)
        cur = nxt
    return None


def _builtin_evidence(ctx: _Context, root: _Root, curated: list[CuratedDir], tainted: Callable[[str], bool],
                      p: Params) -> list[Evidence]:
    """Evidence from the direct children of curated dirs, plus graduation from later dirs.

    Per curated dir: ``hardlink``/``copy_out`` (the file's inode or hash
    falls under exactly one candidate), ``symlink`` (the chain reaches
    exactly one candidate) and ``derived`` (an id-named artifact written
    after the campaign). Derived evidence is skipped for boilerplate (the
    file's hash occurs in >= 2 candidates) and, with ``derived_locality``,
    for a curated dir that is neither local to the campaign (same volume,
    within the root's parent) nor a source of link evidence into it.
    """
    inv = ctx.inv
    cands = {m: posixpath.basename(m) for m in root.group}
    by_token: dict[str, list[str]] = {}
    for m, cid in cands.items():
        for tok in id_tokens(cid):
            by_token.setdefault(tok, []).append(m)

    out: list[Evidence] = []
    for cd in curated:
        links: list[Evidence] = []
        derived: list[Evidence] = []
        for e in inv.children(cd.path):
            if tainted(e.path):
                continue
            if e.kind == "f":
                # Inode numbers are unique per filesystem only: also require the shared inode metadata.
                twins = [x for x in inv.by_inode.get(e.inode, ()) if x.path != e.path and x.kind == "f"
                         and (x.size, x.mtime, x.uid) == (e.size, e.mtime, e.uid)] if e.nlink > 1 else []
                hard = _unique_owner(twins, cands)
                same_sha = inv.by_sha.get(e.sha256, ()) if e.sha256 else ()
                same = _unique_owner(same_sha, cands)
                if hard:
                    links.append(Evidence("hardlink", hard[0], e.path, hard[1], EVIDENCE_WEIGHTS["hardlink"]))
                elif same:
                    links.append(Evidence("copy_out", same[0], e.path, same[1], EVIDENCE_WEIGHTS["copy_out"]))
                boilerplate = len({_owner(x.path, cands) for x in same_sha} - {None}) >= 2
                if e.ext in DERIVED_EXTS and e.mtime > root.t_end and not (p.derived_uniqueness and boilerplate):
                    hits = sorted({m for tok in id_tokens(e.name) for m in by_token.get(tok, ())})
                    derived.extend(Evidence("derived", cands[m], e.path, m, EVIDENCE_WEIGHTS["derived"],
                                            "candidate id in artifact name") for m in hits)
            elif e.kind == "l":
                hit = _follow_symlink(inv, e, cands, p.symlink_max_hops)
                if hit is not None:
                    links.append(Evidence("symlink", hit[0], e.path, hit[1], EVIDENCE_WEIGHTS["symlink"]))
        out.extend(links)
        if not p.derived_locality or links or _is_local(cd.path, root):
            out.extend(derived)
    for d in ctx.outside_roots:
        if d.mtime <= root.t_end or tainted(d.path):
            continue
        for m in sorted({m for tok in id_tokens(d.name) for m in by_token.get(tok, ())}):
            out.append(Evidence("graduation", cands[m], d.path, m, EVIDENCE_WEIGHTS["graduation"],
                                "candidate id reappears in a later directory"))
    return out


def _check_hook_evidence(evidence: Iterable[Evidence], by_id: dict[str, Candidate], root: str) -> list[Evidence]:
    out = []
    for e in evidence:
        if e.kind not in EVIDENCE_KINDS:
            raise ValueError(f"unknown evidence kind {e.kind!r} (expected one of {EVIDENCE_KINDS})")
        if e.candidate not in by_id:
            raise ValueError(f"evidence for unknown candidate {e.candidate!r} in {root}")
        if normalize_path(e.src) != e.src:
            raise ValueError(f"evidence src must be a normalized absolute path: {e.src!r}")
        out.append(e)
    return out


def _cap_coverage(evidence: list[Evidence], n_candidates: int, cap: float, notes: list[str]) -> list[Evidence]:
    """Drop evidence groups that link to at least ``cap`` of all candidates.

    Per kind, a unit is either the evidence directly in one directory or the
    evidence anywhere below one directory (excluding ``/``). Minimal covering
    units (covering, with no covering sub-unit) are dropped; then, if the
    remaining evidence of that kind still covers, it is dropped as a whole.
    """
    kept: list[Evidence] = []
    for kind in sorted({e.kind for e in evidence}):
        items = [e for e in evidence if e.kind == kind]
        units: dict[tuple[str, str], list[Evidence]] = {}
        for e in items:
            d = posixpath.dirname(e.src)
            units.setdefault(("direct", d), []).append(e)
            a = d
            while a != "/":
                units.setdefault(("tree", a), []).append(e)
                a = posixpath.dirname(a)

        covering = {u for u, group in units.items() if len({e.candidate for e in group}) / n_candidates >= cap}
        # A covering tree is minimal unless its direct files or a child tree also cover.
        not_minimal = {("tree", u[1]) for u in covering if u[0] == "direct"}
        not_minimal |= {("tree", posixpath.dirname(u[1])) for u in covering if u[0] == "tree"}
        dropped: set[int] = set()
        for unit in sorted(covering - not_minimal):
            group = units[unit]
            dropped.update(id(e) for e in group)
            share = len({e.candidate for e in group}) / n_candidates
            notes.append(f"dropped {len(group)} {kind} links from {unit[1]}: covers {share:.0%} of "
                         "candidates (mirror/index/pipeline)")
        rest = [e for e in items if id(e) not in dropped]
        share = len({e.candidate for e in rest}) / n_candidates
        if rest and share >= cap:
            notes.append(f"dropped {len(rest)} {kind} links across all curated dirs: covers {share:.0%} of "
                         "candidates (mirror/index/pipeline)")
            continue
        kept.extend(rest)
    return kept


def _label(report: CampaignReport, p: Params) -> None:
    for c in report.candidates:
        c.score = round(sum(e.weight for e in c.evidence), 6)
        c.label = "picked" if c.score >= p.pick_threshold else "unknown"
    picked = [c for c in report.candidates if c.label == "picked"]
    if not picked:
        report.selection_confidence = 0.0
        return
    for c in report.candidates:
        if c.score == 0:
            c.label = "not_picked"
    strength = statistics.fmean(max((e.weight for e in c.evidence), default=0.0) for c in picked)
    report.selection_confidence = round(strength * (1 - len(picked) / report.n_candidates), 6)
    if report.selection_confidence < p.selection_conf:
        for c in report.candidates:
            c.label = "unknown"
        report.notes.append(f"selection confidence {report.selection_confidence:.2f} < {p.selection_conf}: "
                            f"{len(picked)} of {report.n_candidates} would be picked; all labels set to unknown")


def detect(inv: Inventory, *, params: Params | None = None, hooks: Hooks | None = None) -> DetectionResult:
    """Run the full pipeline on ``inv`` (defaults: ``Params()``, ``Hooks()``)."""
    p = params or Params()
    h = hooks or Hooks()
    feats = all_features(inv, tz_offset_s=p.tz_offset_s)
    roots, copies = _campaign_roots(inv, feats, p)
    ctx = _Context(inv, feats, roots, copies)
    reports = []
    for root in roots:
        tainted = functools.cache(functools.partial(is_tainted, anchor=root.path))
        notes = list(root.notes)
        curated = _curated_dirs(ctx, root, p, tainted, notes)
        if not curated:
            notes.append("no curated directories found")
        report = CampaignReport(
            root=root.path, engine=root.engine, era=era(root.t_start), template=root.template,
            n_candidates=len(root.group), uniformity=round(root.uniformity, 6), submitter_uid=root.submitter_uid,
            t_start=root.t_start, t_end=root.t_end, confidence=round(root.confidence, 6), curated_dirs=curated,
            candidates=[Candidate(posixpath.basename(m), m, "unknown", 0.0, [], feats[m]) for m in root.group],
            missing_ids=_missing_ids([posixpath.basename(m) for m in root.group]),
            selection_confidence=0.0, notes=notes,
        )
        by_id = {c.id: c for c in report.candidates}
        evidence = _builtin_evidence(ctx, root, curated, tainted, p)
        for hook in (h.text_mentions, h.graduation):
            evidence += _check_hook_evidence(hook(inv, report), by_id, root.path)
        unique: dict[tuple[str, str, str], Evidence] = {}
        for e in evidence:
            unique.setdefault((e.kind, e.candidate, e.src), e)
        for e in _cap_coverage(list(unique.values()), report.n_candidates, p.coverage_cap, report.notes):
            by_id[e.candidate].evidence.append(e)
        for c in report.candidates:
            c.evidence.sort(key=lambda e: (e.kind, e.src))
        _label(report, p)
        reports.append(report)
    return DetectionResult(campaigns=reports)
