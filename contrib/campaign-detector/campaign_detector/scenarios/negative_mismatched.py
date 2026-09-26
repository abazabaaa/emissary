"""Group B5: curation without a matching campaign.

Thesis: selection evidence must point *into this campaign*. A curated,
approval-worded, working-hours human directory is not itself proof of a pick;
it only counts when its hashes, links or id-token names resolve into a
candidate of the campaign under test. Each scenario removes that connection a
different way: no campaign exists at all, the campaign exists but under a
different id vocabulary, the only nearby "campaign" is not one the MD
detector is built to recognize, or the connection is a bare name coincidence
that the detector's own weak graduation rule should not promote to a pick.

One scenario (``stem_collision``) is a *known* false positive rather than a
papered-over one: two unrelated MD campaigns share the ``run_lig###`` naming
convention, and the detector's derived-evidence matching keys on id tokens
alone, with no notion of "this campaign's volume" -- so notes named after two
KDR ligands, sitting in ABL's own analysis directory (real content: an ABL
analyst's cross-project reference notes), also credit KDR's
identically-numbered candidates even though nothing under ABL points into
KDR at all. That divergence is declared with ``known_gap="derived: ..."``,
and both campaigns' *honest* expectation (zero picks) is still asserted, so
the test fails loudly (``xfail(strict=True)``) rather than passing on a
weakened claim.
"""

from __future__ import annotations

import posixpath

from ..inventory import Inventory
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy, workday,
)
from . import register

# --------------------------------------------------------------------------
# 1. No MD campaign anywhere on the volume.
# --------------------------------------------------------------------------

LIB_ROOT = "/vol7/library/best_papers_final"
LIBRARIAN = 4001
"""uid of the person who keeps the reading library."""


@register(
    kind="negative",
    description="A curated reading library (approval-worded name, working-hours edits, one human uid) has no "
                "MD campaign anywhere on the volume to point into; strongest cue: there is nothing to curate from.",
    expected=ExpectedOutcome.no_campaign(),
)
def build_no_campaign() -> Inventory:
    """A ``best_papers_final`` folder of PDFs and notes with no MD campaign in the tree at all."""
    tb = TreeBuilder(root="/vol7", uid=LIBRARIAN)
    d = tb.dir(LIB_ROOT, uid=LIBRARIAN)
    files = (
        ("kinase_review_final.pdf", 900_000),
        ("binding_affinity_notes.txt", 4_200),
        ("approved_medchem_summary.pdf", 650_000),
        ("README.md", 1_200),
        ("citation_list.csv", 8_000),
    )
    for n, (name, size) in enumerate(files):
        mtime = at(workday(10), 9, 20 * n)
        tb.file(posixpath.join(d, name), size=size, mtime=mtime, uid=LIBRARIAN)
    return tb.build()


# --------------------------------------------------------------------------
# 2. Stem collision across two real MD campaigns on different volumes.
# --------------------------------------------------------------------------

KDR_ROOT = "/vol2/projects/KDR_2011/fep"
ABL_ROOT = "/vol5/archive/ABL_2014/md"

KDR_SUBMITTER = 2101
ABL_SUBMITTER = 2202
ANALYST = 3301

KDR_SPEC = CampaignSpec(
    engine="amber", n_candidates=40, candidate_fmt="run_lig{:03d}", n_chunks=6, chunk_interval_s=6 * 3600,
    chunk_size=1_000_000_000, uid=KDR_SUBMITTER, start=at(0, 3),
)
"""KDR: 40 ligands run_lig001..040 -- includes both lig012 and lig029."""

ABL_SPEC = CampaignSpec(
    engine="amber", n_candidates=20, candidate_fmt="run_lig{:03d}", n_chunks=6, chunk_interval_s=6 * 3600,
    chunk_size=1_000_000_000, uid=ABL_SUBMITTER, start=at(10, 3),
)
"""ABL: only 20 ligands run_lig001..020 -- the same naming scheme as KDR (both start at run_lig001, so
run_lig012 exists under both roots), but run_lig029/run_lig033 exist only in KDR's larger range."""


@register(
    kind="negative",
    description="Two unrelated MD campaigns on different volumes both number their ligands run_lig001... from "
                "one; a real, working-hours, approval-worded analysis folder under ABL holds cross-project "
                "reference notes named after two *KDR* ligands, with no copy, link or hash tying anything under "
                "ABL to either campaign; strongest cue: identical id vocabulary shared by unrelated campaigns.",
    expected=ExpectedOutcome(
        campaign_roots=frozenset({KDR_ROOT, ABL_ROOT}),
        picked={KDR_ROOT: frozenset(), ABL_ROOT: frozenset()},
        present={KDR_ROOT: frozenset({"run_lig029", "run_lig033"}), ABL_ROOT: frozenset({"run_lig012"})},
    ),
    known_gap="derived: derived-evidence id-token matching has no notion of which campaign's volume a file "
              "belongs to, so lig029_compare.png and lig033_handoff_note.txt under ABL's own analysis/ (real "
              "content: an ABL analyst's cross-reference notes about the *other* project) also credit KDR's "
              "identically-numbered run_lig029 and run_lig033, though nothing under ABL points into KDR at all "
              "and ABL itself has no candidates by those numbers",
)
def build_stem_collision() -> Inventory:
    """ABL's analysis/ is real and human-curated but holds only cross-project notes about KDR ligands.

    Nothing here copies, links or hashes into either campaign -- both should honestly report zero picks.
    ``run_lig029``/``run_lig033`` exist only as KDR candidates (ABL's range stops at 020), so a correct
    detector would not credit either campaign; the shared ``run_lig###`` vocabulary lets the id tokens alone
    cross the volume boundary.
    """
    tb = TreeBuilder(root="/")
    md_campaign(tb, KDR_ROOT, KDR_SPEC)
    md_campaign(tb, ABL_ROOT, ABL_SPEC)
    analysis = human_analysis(tb, ABL_ROOT, AnalysisSpec(
        uid=ANALYST, first_workday=25, bursts=2, files=("README.md", "notes.txt", "summary.xlsx"),
    ))
    # Real content: the ABL analyst cross-referencing two KDR ligands in passing -- not a pick of
    # anything under ABL, and ABL has no run_lig029 or run_lig033 of its own to be confused with.
    tb.file(posixpath.join(analysis, "lig029_compare.png"), size=52_000, mtime=at(workday(26), 11), uid=ANALYST)
    tb.file(posixpath.join(analysis, "lig033_handoff_note.txt"), size=3_500, mtime=at(workday(27), 9, 30),
            uid=ANALYST)
    return tb.build()


# --------------------------------------------------------------------------
# 3. Docking poses beside an MD campaign, disjoint id vocabulary.
# --------------------------------------------------------------------------

EGFR_ROOT = "/vol6/projects/EGFR_2016/md"
EGFR_SUBMITTER = 2301
DOCK_HUMAN = 3302

EGFR_SPEC = CampaignSpec(
    engine="amber", n_candidates=24, candidate_fmt="run_lig{:03d}", n_chunks=6, chunk_interval_s=6 * 3600,
    chunk_size=1_000_000_000, uid=EGFR_SUBMITTER, start=at(0, 3),
)


@register(
    kind="negative",
    description="A docking top_poses_final folder sits beside a real MD campaign but names its hits cmpd_#### "
                "-- a completely different id vocabulary from the MD campaign's run_lig###; strongest cue: "
                "disjoint id vocabulary between the human folder and the candidates.",
    expected=ExpectedOutcome.campaign_no_selection(EGFR_ROOT, [f"run_lig{i:03d}" for i in range(1, 25)]),
)
def build_docking_pose_wrong_ids() -> Inventory:
    """``docking/top_poses_final`` curates cmpd_#### docking poses beside an unrelated MD campaign."""
    tb = TreeBuilder(root="/vol6")
    md_campaign(tb, EGFR_ROOT, EGFR_SPEC)
    parent = posixpath.dirname(EGFR_ROOT)
    raw = tb.dir(posixpath.join(parent, "docking", "raw_poses"), uid=DOCK_HUMAN)
    compounds = ("cmpd_0417", "cmpd_0533", "cmpd_0842", "cmpd_1090", "cmpd_1204", "cmpd_1355")
    for n, cmpd in enumerate(compounds):
        tb.file(posixpath.join(raw, f"{cmpd}.sdf"), size=8_000, mtime=at(workday(20), 9, 10 * n), uid=DOCK_HUMAN)
    final = tb.dir(posixpath.join(parent, "docking", "top_poses_final"), uid=DOCK_HUMAN)
    for n, cmpd in enumerate(compounds[:4]):
        tb.copy(posixpath.join(raw, f"{cmpd}.sdf"), posixpath.join(final, f"{cmpd}_pose1.sdf"),
                mtime=at(workday(22), 11, 5 * n), uid=DOCK_HUMAN)
    tb.file(posixpath.join(final, "notes.txt"), size=2_000, mtime=at(workday(22), 11, 30), uid=DOCK_HUMAN)
    return tb.build()


# --------------------------------------------------------------------------
# 4. Copy-outs from a docking (non-MD) campaign.
# --------------------------------------------------------------------------

DOCK_ROOT = "/vol8/docking_campaigns/vs_run7"
DOCK_SUBMITTER = 2401
HITS_HUMAN = 3402


@register(
    kind="negative",
    description="A uniform, templated docking sweep (dock_run_001..060) is genuinely, humanly curated -- "
                "hits_final copies 4 runs out by hash -- but carries no MD file classes or trajectories at all; "
                "strongest cue: non-MD machine fingerprint (no TRAJ), a real selection this detector is not "
                "built to see (a docking detector would).",
    expected=ExpectedOutcome.no_campaign(),
)
def build_docking_only_campaign() -> Inventory:
    """60 uniform docking run dirs plus a real, hash-verified ``hits_final`` selection of 4."""
    tb = TreeBuilder(root="/vol8", uid=DOCK_SUBMITTER)
    for i in range(1, 61):
        cid = f"dock_run_{i:03d}"
        d = tb.dir(posixpath.join(DOCK_ROOT, cid), uid=DOCK_SUBMITTER)
        base = at(30, 2) + i * 300
        tb.file(posixpath.join(d, "receptor.pdbqt"), size=40_000, mtime=base, uid=DOCK_SUBMITTER)
        tb.file(posixpath.join(d, "ligand.pdbqt"), size=6_000, mtime=base + 30, uid=DOCK_SUBMITTER)
        tb.file(posixpath.join(d, "out.pdbqt"), size=9_000, mtime=base + 90, uid=DOCK_SUBMITTER)
        tb.file(posixpath.join(d, "log.txt"), size=3_000, mtime=base + 100, uid=DOCK_SUBMITTER)
    hits = tb.dir(posixpath.join(DOCK_ROOT, "hits_final"), uid=HITS_HUMAN)
    picks = ["dock_run_007", "dock_run_018", "dock_run_033", "dock_run_051"]
    pick_by_copy(tb, campaign_root=DOCK_ROOT, dst_dir=hits, cids=picks, src_name="out.pdbqt",
                 rename="{cid}_out.pdbqt", uid=HITS_HUMAN, mtime=at(workday(45), 10))
    tb.file(posixpath.join(hits, "summary.txt"), size=1_500, mtime=at(workday(45), 10, 30), uid=HITS_HUMAN)
    return tb.build()


# --------------------------------------------------------------------------
# 5. Graduation false friend: name-only coincidence, no link into the campaign.
# --------------------------------------------------------------------------

JAK2_ROOT = "/vol1/projects/JAK2_2013/fep"
JAK2_SUBMITTER = 2501
PROGRAMS_OWNER = 3502


@register(
    kind="negative",
    description="A later chemistry-program folder named after a ligand series (lig012_series, mtime after the "
                "campaign) reuses a candidate id by pure name coincidence; the built-in graduation rule is a "
                "weak (0.5) signal by design and an archivist's say-so alone must not turn it into a pick; "
                "strongest cue: name-only coincidence with no hash, link or content connection to the campaign.",
    expected=ExpectedOutcome.campaign_no_selection(JAK2_ROOT, [f"run_lig{i:03d}" for i in range(1, 41)]),
)
def build_graduation_false_friend() -> Inventory:
    """A campaign with no analysis dir at all, plus an unrelated later program folder sharing lig012's name."""
    tb = TreeBuilder(root="/vol1", uid=JAK2_SUBMITTER)
    md_campaign(tb, JAK2_ROOT, CampaignSpec(
        engine="amber", n_candidates=40, candidate_fmt="run_lig{:03d}", n_chunks=6, chunk_interval_s=6 * 3600,
        chunk_size=1_000_000_000, uid=JAK2_SUBMITTER, start=at(0, 3),
    ))
    programs = tb.dir("/vol9/programs/lig012_series", uid=PROGRAMS_OWNER)
    tb.file(posixpath.join(programs, "charter.md"), size=4_000, mtime=at(workday(60), 9), uid=PROGRAMS_OWNER)
    tb.file(posixpath.join(programs, "roadmap.pptx"), size=500_000, mtime=at(workday(60), 9, 30),
            uid=PROGRAMS_OWNER)
    return tb.build()
