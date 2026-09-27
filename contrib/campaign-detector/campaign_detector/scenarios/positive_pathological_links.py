"""Positive twins of group B6 -- structural pathologies that still hide a real campaign and a real pick.

Each scenario here sits just across a boundary drawn by a negative in
:mod:`negative_pathological`: a symlink chain that does end inside one
candidate, a link to a candidate's replica subdirectory, exactly
``min_candidates`` runs, four sibling runs at depth 30, a campaign inside a
3,000-file flat dump, and four co-submitted runs whose folder names are
shared with (or outnumbered by) unrelated project folders. Every expectation
pins the exact candidate set (picked, not_picked, and no unknowns) so a
detector that finds the right root with the wrong members still fails.

Adversarial review
------------------
Created by the reviewer from the writer's three documented judgement calls
(symlink chain, numbered subset, headcount boundary) plus four twins
(replica-dir link, depth 30, flat dump, minority template). The honest answer is encoded even where the
detector disagrees: the 10-hop chain into ``run_cpd003`` is a pick to anyone
who follows it (``resolved_target`` follows one hop, known gap), and four
same-uid, same-week AMBER runs are a small campaign whether their names
share ``proj_###`` with 26 unrelated folders or form an outnumbered
``proj_###_md`` group (``sibling_uniformity`` scores only the largest
template group, known gaps). Verified, not assumed: a link to a directory
``run_lig003/rep2`` is inside the candidate (``_owner`` walks up the path,
and the per-ligand replica roots are folded into the outer campaign); the
four-candidate boundary, a depth-31 root and a campaign surrounded by 3,000
loose files including ``.nc``/``.prmtop``/``.log`` are all detected with the
right pick. Each known-gap scenario was also checked counterfactually: with
the unrelated folders removed, or the chain cut to one hop, the detector
matches the expectation exactly, so each fails only for its stated reason.
Tried and could not break: flat noise does not leak into member
signatures or trajectory byte fractions (both read only member dirs), and
the dump dir itself scores as "curated" yet contributes no evidence because
none of its files share a hash, inode or id token with a candidate.
"""

from __future__ import annotations

import dataclasses
import posixpath
from collections.abc import Iterable

from ..inventory import Inventory, normalize_path
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy,
    pick_by_derived, workday,
)
from . import register
from .negative_pathological import (
    GPCR_ROOT, GPCR_SPEC, TEMPLATED_SEGMENTS, TINY_SPEC, flat_dump, link_chain, misc_project,
    tiny_campaign,
)


def exact(root: str, picked: Iterable[str], not_picked: Iterable[str]) -> ExpectedOutcome:
    """One campaign at ``root`` whose candidates are exactly ``picked`` + ``not_picked``, none unknown."""
    root = normalize_path(root)
    return ExpectedOutcome(campaign_roots=frozenset({root}), picked={root: frozenset(picked)},
                           not_picked={root: frozenset(not_picked)}, unknown={root: frozenset()})


def _ids(fmt: str, idx: Iterable[int]) -> list[str]:
    return [fmt.format(i) for i in idx]


# --------------------------------------------------------------------------
# Symlinks: a long chain into one candidate, and a link to a replica subdir.
# --------------------------------------------------------------------------

_GPCR_CANDS = _ids("run_cpd{:03d}", range(1, 7))


@register(
    kind="positive",
    description=(
        "An analyst's analysis/legacy_link reaches run_cpd003/prod001.nc through a 10-hop symlink chain "
        "(an old link farm), which is a pick of cpd003 to anyone who follows it; strongest cue: the chain's "
        "final target lies inside exactly one candidate."
    ),
    expected=exact(GPCR_ROOT, ["run_cpd003"], [c for c in _GPCR_CANDS if c != "run_cpd003"]),
    known_gap="symlink: chains are resolved one hop only; a chain ending inside exactly one candidate should count",
)
def build_symlink_chain_pick() -> Inventory:
    """The writer's GPCR campaign with a clean 10-hop chain from analysis/ into ``run_cpd003``."""
    tb = TreeBuilder(root="/vol5")
    names = md_campaign(tb, GPCR_ROOT, GPCR_SPEC)
    analysis = human_analysis(tb, GPCR_ROOT, AnalysisSpec(uid=7501, first_workday=300, bursts=3))
    target = posixpath.join(GPCR_ROOT, names[2], "prod001.nc")
    head = link_chain(tb, "/vol5/linkfarm", target, 10, uid=7501, mtime=at(workday(300), 9))
    tb.symlink(posixpath.join(analysis, "legacy_link"), head, mtime=at(workday(300), 11), uid=7501)
    return tb.build()


REPLICA_ROOT = "/vol5/projects/BRD4_2013/md"
REPLICA_SPEC = CampaignSpec(engine="gromacs", n_candidates=8, candidate_fmt="run_lig{:03d}", inner_fmt="rep{}",
                            n_inner=4, n_chunks=6, uid=7101, start=at(700, 3))
"""8 ligands x 4 replicas: each ``run_lig###`` is a replica-level root that must fold into the outer one."""


@register(
    kind="positive",
    description=(
        "8 GROMACS ligands in four replicas each, where the analyst symlinks the directory run_lig003/rep2 "
        "(the one replica they inspected), is a pick of lig003; strongest cue: a link into a replica "
        "subdirectory is inside that candidate."
    ),
    expected=exact(REPLICA_ROOT, ["run_lig003"], [c for c in _ids("run_lig{:03d}", range(1, 9)) if c != "run_lig003"]),
)
def build_symlink_to_replica() -> Inventory:
    """A directory symlink ``analysis/lig003_rep2 -> ../run_lig003/rep2/`` (trailing slash kept)."""
    tb = TreeBuilder(root="/vol5")
    md_campaign(tb, REPLICA_ROOT, REPLICA_SPEC)
    analysis = human_analysis(tb, REPLICA_ROOT, AnalysisSpec(uid=7601, first_workday=520, bursts=3))
    tb.symlink(posixpath.join(analysis, "lig003_rep2"), "../run_lig003/rep2/", mtime=at(workday(522), 15),
               uid=7601)
    return tb.build()


# --------------------------------------------------------------------------
# Boundaries: exactly min_candidates, and depth 30.
# --------------------------------------------------------------------------

BOUNDARY_ROOT = "/vol4/legacy/four_campaign/data"


@register(
    kind="positive",
    description=(
        "Four AMBER runs with an analyst's copy-out of run_x001 are the smallest campaign the detector "
        "promises to find; strongest cue: exactly min_candidates=4 uniform siblings (the 3-run twin is negative)."
    ),
    expected=exact(BOUNDARY_ROOT, ["run_x001"], ["run_x002", "run_x003", "run_x004"]),
)
def build_four_candidates_boundary() -> Inventory:
    """``negative_pathological.few_candidates_with_pick`` with a fourth run."""
    tb = TreeBuilder(root="/vol4")
    tiny_campaign(tb, BOUNDARY_ROOT, dataclasses.replace(TINY_SPEC, n_candidates=4))
    return tb.build()


DEEP_ROOT = "/vol7/" + "/".join(TEMPLATED_SEGMENTS)


@register(
    kind="positive",
    description=(
        "Four sibling AMBER runs at the bottom of a 30-deep level01/.../level30 chain, with RMSD plots of "
        "run03 in analysis/, are a campaign and a pick; strongest cue: depth alone never blocks detection."
    ),
    expected=exact(DEEP_ROOT, ["run03"], ["run01", "run02", "run04"]),
)
def build_deep_chain_campaign() -> Inventory:
    """``negative_pathological.deep_chain_templated`` with four sibling runs at the leaf."""
    tb = TreeBuilder(root="/vol7")
    md_campaign(tb, DEEP_ROOT, CampaignSpec(engine="amber", n_candidates=4, candidate_fmt="run{:02d}", n_chunks=5,
                                            uid=1201, start=at(0, 3)))
    analysis = human_analysis(tb, DEEP_ROOT, AnalysisSpec(uid=1601, first_workday=10, bursts=2))
    pick_by_derived(tb, analysis, ["run03"], suffix="_rmsd.png", uid=1601, mtime=at(workday(12), 10))
    pick_by_derived(tb, analysis, ["run03"], suffix="_contacts.png", uid=1601, mtime=at(workday(12), 10, 30))
    return tb.build()


# --------------------------------------------------------------------------
# Flat noise around a campaign.
# --------------------------------------------------------------------------

FLAT_CAMPAIGN_ROOT = "/vol6/dump/raw"


@register(
    kind="positive",
    description=(
        "Four templated NAMD run dirs sitting inside a 3,000-file flat dump (loose .nc/.dcd/.prmtop/.log "
        "from 20 uids), one hard-linked into analysis/, are a campaign with a pick; strongest cue: the run "
        "dirs are uniform siblings, and loose files around them are not members."
    ),
    expected=exact(FLAT_CAMPAIGN_ROOT, ["run_lig002"], ["run_lig001", "run_lig003", "run_lig004"]),
)
def build_flat_dump_campaign() -> Inventory:
    """``negative_pathological.huge_flat_mixed`` plus four NAMD runs and a hard-link pick."""
    tb = TreeBuilder(root="/vol6")
    flat_dump(tb, FLAT_CAMPAIGN_ROOT)
    md_campaign(tb, FLAT_CAMPAIGN_ROOT, CampaignSpec(engine="namd", n_candidates=4, n_chunks=8, uid=6501,
                                                     start=at(1200, 3)))
    analysis = human_analysis(tb, "/vol6/dump", AnalysisSpec(uid=6601, first_workday=880, bursts=2))
    tb.hardlink(posixpath.join(FLAT_CAMPAIGN_ROOT, "run_lig002", "prod008.dcd"),
                posixpath.join(analysis, "lig002_final.dcd"))
    return tb.build()


# --------------------------------------------------------------------------
# A small campaign whose folder names do not isolate it.
# --------------------------------------------------------------------------

POOL_ROOT = "/vol2/archive/proj_pool"


def _pool(tb: TreeBuilder, root: str, md_fmt: str, md_idx: Iterable[int], misc_idx: Iterable[int]) -> list[str]:
    for i in misc_idx:
        misc_project(tb, root, i)
    idx = list(md_idx)
    names = md_campaign(tb, root, CampaignSpec(engine="amber", n_candidates=max(idx), candidate_fmt=md_fmt,
                                               skip=frozenset(range(1, max(idx) + 1)) - set(idx), n_chunks=6,
                                               uid=2101, start=at(100, 3)))
    review = human_analysis(tb, posixpath.dirname(root), AnalysisSpec(uid=2901, first_workday=100,
                                                                        dirname="md_review"))
    pick_by_copy(tb, root, review, [names[1]], src_name="prod006.nc", rename="best_pose_run2.nc", uid=2901,
                 mtime=at(workday(101), 14))
    return names


@register(
    kind="positive",
    description=(
        "proj_001..proj_004 hold four AMBER runs submitted by one uid in one hour (one copied out for review) "
        "among 26 unrelated proj_### folders, which is a small campaign sharing a numbering scheme; strongest "
        "cue: a same-signature, single-submitter, co-temporal subset of >=4 siblings."
    ),
    expected=exact(POOL_ROOT, ["proj_002"], ["proj_001", "proj_003", "proj_004"]),
    known_gap="campaign_root: uniform subset inside a heterogeneous template group is not isolated",
)
def build_numbered_siblings_md_subset() -> Inventory:
    """The writer's original ``numbered_siblings_heterogeneous`` tree plus a copy-out of ``proj_002``."""
    tb = TreeBuilder(root="/vol2")
    _pool(tb, POOL_ROOT, "proj_{:03d}", range(1, 5), range(5, 31))
    return tb.build()


MINORITY_ROOT = "/vol9/groupshare/projects"


@register(
    kind="positive",
    description=(
        "Four co-submitted AMBER runs named proj_031_md..proj_034_md next to 30 unrelated proj_### folders, "
        "one copied out for review, are a campaign with its own finer template; strongest cue: a distinct "
        "template group of >=4 uniform runs, however outnumbered."
    ),
    expected=exact(MINORITY_ROOT, ["proj_032_md"], ["proj_031_md", "proj_033_md", "proj_034_md"]),
    known_gap=("campaign_root: only the largest template group of a parent is evaluated, so a minority group "
               "of uniform runs is never scored (and would fail template_fraction=0.6 if it were)"),
)
def build_minority_template_campaign() -> Inventory:
    """34 children: proj_001..proj_030 (non-MD) and proj_031_md..proj_034_md (one AMBER batch)."""
    tb = TreeBuilder(root="/vol9")
    _pool(tb, MINORITY_ROOT, "proj_{:03d}_md", range(31, 35), range(1, 31))
    return tb.build()
