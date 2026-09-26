"""Negative group B6 -- structural pathologies.

Thesis of the group: odd directory *shapes* must neither crash the detector
nor be misread as a campaign. Each scenario below removes exactly one of the
things a real campaign needs (siblings, uniformity, headcount, structure, MD
file classes, or safe link resolution) while looking superficially plausible,
so the detector's rejection has to come from the right gate, not luck.
"""

from __future__ import annotations

import posixpath

from ..inventory import Inventory
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy,
    workday,
)
from . import register

# --------------------------------------------------------------------------
# 1. Deep single chains: never enough siblings to reach min_candidates.
# --------------------------------------------------------------------------

ARBITRARY_SEGMENTS = tuple(chr(ord("a") + i) for i in range(26)) + ("aa", "bb", "cc", "dd")
"""30 distinct, non-digit path segments: /vol1/a/b/c/.../z/aa/bb/cc/dd."""

TEMPLATED_SEGMENTS = tuple(f"level{i:02d}" for i in range(1, 31))
"""30 nested, digit-templated segments, still exactly one child per level."""


@register(
    kind="negative",
    description=(
        "A 30-level single chain of arbitrarily-named directories ends in one lone AMBER run; "
        "the strongest cue is that no directory anywhere on the path ever has more than one child, "
        "so min_candidates=4 is never reached at any depth."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_deep_chain_arbitrary() -> Inventory:
    """One AMBER run at the bottom of a 30-deep chain of one-child directories."""
    tb = TreeBuilder(root="/vol1")
    bottom = "/vol1/" + "/".join(ARBITRARY_SEGMENTS)
    md_campaign(tb, bottom, CampaignSpec(engine="amber", n_candidates=1, candidate_fmt="lone_run", n_chunks=5,
                                         uid=1101, start=at(0, 3)))
    return tb.build()


@register(
    kind="negative",
    description=(
        "The same 30-deep single chain, but every level is machine-templated (level01/level02/...); "
        "the strongest cue is still no siblings -- a templated name alone never creates a sibling group."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_deep_chain_templated() -> Inventory:
    """One AMBER run at the bottom of a 30-deep chain of templated one-child directories."""
    tb = TreeBuilder(root="/vol7")
    bottom = "/vol7/" + "/".join(TEMPLATED_SEGMENTS)
    md_campaign(tb, bottom, CampaignSpec(engine="amber", n_candidates=1, candidate_fmt="run01", n_chunks=5,
                                         uid=1201, start=at(0, 3)))
    return tb.build()


# --------------------------------------------------------------------------
# 2. Numbered siblings, heterogeneous contents: template covers all, uniformity does not.
# --------------------------------------------------------------------------

PROJ_ROOT = "/vol2/archive/proj_pool"

_DOCKING_FILES = ("vina_out.pdbqt", "receptor.pdb", "poses.sdf", "scores.csv")
_SHEET_FILES = ("dG_summary.xlsx", "raw_data.csv")
_PHOTO_FILES = ("img001.jpg", "img002.jpg", "poster.png")
_NOTE_FILES = ("readme.txt",)
_MIXED_FILES = ("scratch.log", "plan.md")
_MISC_PATTERNS = (_DOCKING_FILES, _SHEET_FILES, _PHOTO_FILES, _NOTE_FILES, _MIXED_FILES)


@register(
    kind="negative",
    description=(
        "30 proj_### siblings all share one name template (template_fraction=1.0), but only 4 hold full "
        "AMBER runs while the other 26 hold docking output, spreadsheets, photos and notes from many uids "
        "over several years; the strongest cue is signature uniformity collapsing far below the 0.75 gate."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_numbered_siblings_heterogeneous() -> Inventory:
    """proj_001..proj_004 are real AMBER runs; proj_005..proj_030 are unrelated, varied contents.

    The four real runs are a plausible sub-campaign to a human archivist, but the detector groups
    siblings by name template only: since all 30 share the same ``proj_#`` template, it never
    isolates that size-4 subset, and the mixed group's uniformity is nowhere near 0.75.
    """
    tb = TreeBuilder(root="/vol2")
    md_campaign(tb, PROJ_ROOT, CampaignSpec(engine="amber", n_candidates=4, candidate_fmt="proj_{:03d}",
                                            n_chunks=6, uid=2101, start=at(100, 3)))
    for i in range(5, 31):
        d = f"{PROJ_ROOT}/proj_{i:03d}"
        pattern = _MISC_PATTERNS[i % len(_MISC_PATTERNS)]
        uid = 2100 + i
        mtime = at((i - 5) * 91, 10)  # roughly quarterly, spread across ~6.5 years
        for n, name in enumerate(pattern):
            tb.file(f"{d}/{name}", size=2_000 + n * 500, mtime=mtime + n * 60, uid=uid)
    return tb.build()


# --------------------------------------------------------------------------
# 3. Below min_candidates, even with a real human pick.
# --------------------------------------------------------------------------

TINY_ROOT = "/vol4/legacy/tiny_campaign/data"


@register(
    kind="negative",
    description=(
        "Only 3 candidate run dirs -- one short of min_candidates=4 -- even though a human analysis/ "
        "copies one of them out exactly as in the grounded positive; the strongest cue is the headcount "
        "floor, not the absence of a genuine pick."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_few_candidates_with_pick() -> Inventory:
    """3 AMBER runs plus a real copy-out pick; an archivist would call this a tiny campaign with a pick.

    The detector's rule is a hard floor on candidate count (README: min_candidates=4), so this is a
    deliberate, documented judgement call: we register the honest ``no_campaign()`` expectation the
    rule produces, not what an archivist skimming 3 well-formed runs and a pick would conclude.
    """
    tb = TreeBuilder(root="/vol4")
    names = md_campaign(tb, TINY_ROOT, CampaignSpec(engine="amber", n_candidates=3, candidate_fmt="run_x{:03d}",
                                                     n_chunks=6, uid=9001, start=at(500, 3)))
    analysis = human_analysis(tb, TINY_ROOT, AnalysisSpec(uid=9501, first_workday=600, bursts=2))
    pick_by_copy(tb, TINY_ROOT, analysis, names[:1], src_name="prod001.nc", uid=9501, mtime=at(workday(600), 11))
    return tb.build()


# --------------------------------------------------------------------------
# 4. Huge flat mixed directory: no subdirectories at all.
# --------------------------------------------------------------------------

_FLAT_ROOT = "/vol6/dump/raw"
_FLAT_EXTS = (".nc", ".prmtop", ".png", ".pdf", ".xlsx", ".txt", ".csv", ".dcd", ".log")
_FLAT_UIDS = tuple(range(6001, 6021))


@register(
    kind="negative",
    description=(
        "One flat directory holds 3,000 files of mixed extensions from 20 uids spread over years, with "
        "zero subdirectories; the strongest cue is n_dirs=0 -- there is no sibling group to evaluate at all."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_huge_flat_mixed() -> Inventory:
    """A single directory of 3,000 mixed files and no subdirectories."""
    tb = TreeBuilder(root="/vol6")
    for i in range(3000):
        ext = _FLAT_EXTS[i % len(_FLAT_EXTS)]
        uid = _FLAT_UIDS[i % len(_FLAT_UIDS)]
        day = (i * 37) % (365 * 8)  # deterministic spread across roughly 8 years
        mtime = at(day, 9 + (i % 8))
        size = 1_024 + (i % 50) * 997
        tb.file(f"{_FLAT_ROOT}/file_{i:05d}{ext}", size=size, mtime=mtime, uid=uid)
    return tb.build()


# --------------------------------------------------------------------------
# 5. Uniform, templated, but zero MD file classes.
# --------------------------------------------------------------------------

NOTES_ROOT = "/vol8/shared/meeting_notes"
MEETING_DATES = ("2011-03-04", "2011-03-11", "2011-03-18", "2011-03-25", "2011-04-01",
                  "2011-04-08", "2011-04-15", "2011-04-22", "2011-04-29", "2011-05-06")


@register(
    kind="negative",
    description=(
        "10 date-named meeting-notes dirs are templated by digits and perfectly uniform (notes.txt, "
        "agenda.docx, slides.pptx in every one); the strongest cue is zero MD file classes, so the "
        ">=3-classes-including-TRAJ gate rejects it before uniformity even matters."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_dated_meeting_notes() -> Inventory:
    """10 weekly meeting-notes directories, uniform but entirely non-MD content."""
    tb = TreeBuilder(root="/vol8")
    for i, date in enumerate(MEETING_DATES):
        d = f"{NOTES_ROOT}/{date}"
        mtime = at(400 + i * 7, 14)
        tb.file(f"{d}/notes.txt", size=3_000, mtime=mtime, uid=8001)
        tb.file(f"{d}/agenda.docx", size=15_000, mtime=mtime - 3600, uid=8001)
        tb.file(f"{d}/slides.pptx", size=500_000, mtime=mtime + 1800, uid=8002)
    return tb.build()


# --------------------------------------------------------------------------
# 6. Symlink loops, self-references, dangling links and an un-followed chain.
# --------------------------------------------------------------------------

GPCR_ROOT = "/vol5/projects/GPCR_2012/screen"


@register(
    kind="negative",
    description=(
        "A real 6-candidate AMBER campaign sits under symlink pathology (a self-loop, a dir linking to "
        "itself, dangling targets, and a 10-hop chain from a curated-looking analysis/ into a real "
        "candidate file); the strongest cue is that resolved_target() follows exactly one hop, so the "
        "chain -- which an archivist reading it end to end would call a pick -- yields no evidence and "
        "none of the pathological links crash the detector."
    ),
    expected=ExpectedOutcome.campaign_no_selection(
        GPCR_ROOT, cids=[f"run_cpd{i:03d}" for i in range(1, 7)]
    ),
)
def build_symlink_pathology() -> Inventory:
    """A real campaign plus symlink loops/self-refs/dangling links/a chain the detector cannot follow.

    ``analysis/legacy_link`` starts a 10-symlink chain (legacy_link -> h10/link -> h09/link -> ... ->
    h02/link -> run_cpd003/prod001.nc) that ends inside a real candidate. An archivist who followed the
    chain by hand would call it a pick by symlink. ``Entry.resolved_target()`` is documented to resolve
    exactly one hop (see README/inventory.py), so the detector only ever sees legacy_link's immediate
    target -- a symlink elsewhere, not a candidate path -- and correctly produces no evidence. This is
    a deliberate, honest judgement call rather than a ``known_gap``: the framework requires a scenario
    in this module to expect no picks (``kind="negative"``), so we cannot register "should have picked
    run_cpd003" as the expectation here without mischaracterising the scenario's kind; a reviewer who
    considers chain-following in scope should promote this to its own positive scenario with a
    ``known_gap="symlink: chains not followed"`` instead of relying on this one.
    """
    tb = TreeBuilder(root="/vol5")
    names = md_campaign(tb, GPCR_ROOT, CampaignSpec(engine="amber", n_candidates=6, candidate_fmt="run_cpd{:03d}",
                                                     n_chunks=8, uid=7001, start=at(200, 3)))
    analysis = human_analysis(tb, GPCR_ROOT, AnalysisSpec(uid=7501, first_workday=300, bursts=3))

    # A directory that links to itself, and one whose only entry loops back to its own parent.
    tb.symlink("/vol5/misc/a/loop", "../a", mtime=at(190, 0), uid=7001)
    tb.symlink("/vol5/misc/b/self", ".", mtime=at(190, 0), uid=7001)
    # Dangling targets: nothing in the inventory lives at either destination.
    tb.symlink("/vol5/misc/dangling1", "/vol5/nowhere/ghost1.nc", mtime=at(190, 0), uid=7001)
    tb.symlink("/vol5/misc/dangling2", "/vol5/also_missing/ghost2.rst7", mtime=at(190, 0), uid=7001)

    # A 10-hop symlink chain, each hop alone in its own directory so no intermediate hop is ever a
    # direct child of a curated directory (which would let a single extra hop resolve "by accident").
    target = posixpath.join(GPCR_ROOT, names[2], "prod001.nc")
    chain_mtime = at(workday(300), 9)
    prev = target
    for n in range(10, 1, -1):
        hop_path = f"/vol5/linkfarm/h{n:02d}/link"
        tb.symlink(hop_path, prev, mtime=chain_mtime, uid=7501)
        prev = hop_path
    tb.symlink(posixpath.join(analysis, "legacy_link"), prev, mtime=at(workday(300), 11), uid=7501)

    return tb.build()
