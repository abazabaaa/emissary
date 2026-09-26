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


def _evaluate_root(inv: Inventory, feats: dict[str, DirFeatures], path: str, p: Params) -> _Root | None:
    if feats[path].n_dirs < p.min_candidates:
        return None
    group, uniformity, tfrac, mode_sig = sibling_uniformity(inv, feats, path)
    classes = {s.split(":", 1)[0] for s in mode_sig}
    if (len(group) < p.min_candidates or tfrac < p.template_fraction or uniformity < p.uniformity
            or len(classes) < p.min_md_classes or "TRAJ" not in classes):
        return None
    files = [f for m in group for f in files_within(inv, m, 2)]
    total = sum(f.size for f in files)
    trajs = [f for f in files if classify(f) == "TRAJ"]
    traj_frac = sum(f.size for f in trajs) / total if total else 0.0
    submitter, purity = dominant(f.uid for f in files)
    if traj_frac < p.traj_byte_fraction or purity < p.uid_purity:
        return None
    regs = [feats[m].traj_chunk_regularity for m in group if feats[m].traj_chunk_regularity is not None]
    reg = statistics.fmean(regs) if regs else 0.0
    md_classes = len(classes & set(MD_CLASS_NAMES))
    confidence = 0.3 * uniformity + 0.2 * md_classes / 6 + 0.2 * traj_frac + 0.15 * reg + 0.15 * purity
    if confidence < p.campaign_conf:
        return None
    notes = []
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
    )


def _is_replica_level(template: str) -> bool:
    return bool(set(tokens(template)) & REPLICA_WORDS)


def _find_roots(inv: Inventory, feats: dict[str, DirFeatures], p: Params) -> list[_Root]:
    """Qualifying roots, deepest first; an outer root absorbs roots inside its members.

    Exception: when at least half of the members hold an inner root whose
    members are not a replica level (``rep#``, ``lambda_#.#``...), the
    members are campaigns in their own right (``batch1..batch4``) and the
    outer directory is not a root.
    """
    found: dict[str, _Root] = {}
    for d in sorted(inv.dirs(), key=lambda e: (-feats[e.path].depth, e.path)):
        root = _evaluate_root(inv, feats, d.path, p)
        if root is None:
            continue
        inner = [r for r in found.values() if any(is_within(r.path, m) for m in root.group)]
        campaigns = {m for m in root.group for r in inner
                     if is_within(r.path, m) and not _is_replica_level(r.template)}
        if 2 * len(campaigns) >= len(root.group):
            continue
        for r in inner:
            del found[r.path]
        found[d.path] = root
    return [found[k] for k in sorted(found)]


def _split_copies(roots: list[_Root], p: Params) -> tuple[list[_Root], list[_Root]]:
    """Separate campaigns from later byte-identical copies of other campaigns.

    A root is a copy when at least ``copy_overlap`` of its trajectory hashes
    occur in another root whose chunks were created (ctime) earlier; the
    original gets a note.
    """
    copies: list[_Root] = []
    for r in roots:
        for other in roots:
            if other is r or not r.traj_shas or other.first_ctime >= r.first_ctime:
                continue
            overlap = len(r.traj_shas & other.traj_shas) / len(r.traj_shas)
            if overlap >= p.copy_overlap:
                copies.append(r)
                other.notes.append(f"ignored {r.path}: {overlap:.0%} of its trajectory chunks are later copies "
                                   "of this campaign's (mirror/backup)")
                break
    return [r for r in roots if r not in copies], copies


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


def _curated_dirs(ctx: _Context, root: _Root, p: Params, tainted: Callable[[str], bool]) -> list[CuratedDir]:
    """Score untainted non-candidate dirs; files and symlinks both count as entries."""
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
        if len(reasons) >= p.curated_score:
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


def _builtin_evidence(ctx: _Context, root: _Root, curated: list[CuratedDir],
                      tainted: Callable[[str], bool]) -> list[Evidence]:
    inv = ctx.inv
    cands = {m: posixpath.basename(m) for m in root.group}
    by_token: dict[str, list[str]] = {}
    for m, cid in cands.items():
        for tok in id_tokens(cid):
            by_token.setdefault(tok, []).append(m)

    out: list[Evidence] = []
    for cd in curated:
        for e in inv.children(cd.path):
            if tainted(e.path):
                continue
            if e.kind == "f":
                # Inode numbers are unique per filesystem only: also require the shared inode metadata.
                twins = [x for x in inv.by_inode.get(e.inode, ()) if x.path != e.path and x.kind == "f"
                         and (x.size, x.mtime, x.uid) == (e.size, e.mtime, e.uid)] if e.nlink > 1 else []
                hard = _unique_owner(twins, cands)
                same = _unique_owner(inv.by_sha.get(e.sha256, ()), cands) if e.sha256 else None
                if hard:
                    out.append(Evidence("hardlink", hard[0], e.path, hard[1], EVIDENCE_WEIGHTS["hardlink"]))
                elif same:
                    out.append(Evidence("copy_out", same[0], e.path, same[1], EVIDENCE_WEIGHTS["copy_out"]))
                if e.ext in DERIVED_EXTS and e.mtime > root.t_end:
                    hits = sorted({m for tok in id_tokens(e.name) for m in by_token.get(tok, ())})
                    out.extend(Evidence("derived", cands[m], e.path, m, EVIDENCE_WEIGHTS["derived"],
                                        "candidate id in artifact name") for m in hits)
            elif e.kind == "l":
                tgt = e.resolved_target()
                cid = _owner(tgt, cands) if tgt else None
                if cid is not None:
                    out.append(Evidence("symlink", cid, e.path, str(tgt), EVIDENCE_WEIGHTS["symlink"]))
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
    roots, copies = _split_copies(_find_roots(inv, feats, p), p)
    ctx = _Context(inv, feats, roots, copies)
    reports = []
    for root in roots:
        tainted = functools.cache(functools.partial(is_tainted, anchor=root.path))
        curated = _curated_dirs(ctx, root, p, tainted)
        notes = list(root.notes)
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
        evidence = _builtin_evidence(ctx, root, curated, tainted)
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
