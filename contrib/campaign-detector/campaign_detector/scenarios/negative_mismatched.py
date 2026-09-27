"""Group B5: curation without a matching campaign.

Thesis: selection evidence must point *into this campaign*. A curated,
approval-worded, working-hours human directory is not itself proof of a pick;
it only counts when its hashes, links or id-token names resolve into a
candidate of the campaign under test. Each scenario removes that connection a
different way: no campaign exists at all; a campaign exists but the curated
folder is far away in its own tree or on another volume and names compounds
of another numbering; the folder is local but uses a different id vocabulary
(or the same numbers under a different prefix); the only nearby "campaign" is
not one the MD detector is built to recognize; or the connection is a bare
name coincidence that the weak graduation rule should not promote to a pick.

Adversarial review
------------------

What changed. (1) Every campaign now runs in the era its path names
(``KDR_2011`` in 2011, ``ABL_2014`` in 2014, ...), so ``era`` in reports is
no longer 2020 for all of them. (2) ``stem_collision`` was re-grounded: the
writer's story ("an ABL analyst's notes about *KDR* ligands") would, if true,
be a real cross-project reference to KDR and arguably a KDR selection; now
``lig029``/``lig033`` are ABL med-chem register numbers the ABL analyst is
triaging for the *next* ABL batch (ABL simulated only 1..20), which is the
situation an archivist actually meets and is unambiguously not a KDR pick.
(3) Added ``library_beside_unrelated_md`` (same volume, curated folder three
levels from the campaign, notes naming a *third* project's compounds with
colliding ``lig###`` tokens), ``docking_pose_same_numbers`` (local docking
folder whose ``cmpd012`` numbers equal the MD ``run_lig012`` numbers but in
the docking screen's own namespace), and ``graduation_false_friend_summary``
(the coincidental ``lig012_series`` folder also holds ``lig012_summary.xlsx``,
so one name coincidence is counted twice: derived 0.7 + graduation 0.5 = 1.2).
(4) ``docking_only_campaign`` now carries three MD file classes (``vina.conf``
INPUT, ``dock.log`` LOG, ``slurm-<id>.out`` SCHED), so it passes the
``min_md_classes`` gate and only the absence of trajectories keeps it out
(that one absence trips two gates, no TRAJ class in the modal signature and a
trajectory byte fraction of 0; neither can be isolated without inventing an
MD trajectory a docking sweep would not have).
(5) ``docking_pose_wrong_ids`` curated files are now derived-ext plots and
sheets without an underscore in the id (``cmpd0417_pose1.png``), so id tokens
are actually extracted and compared instead of never forming.
(6) The graduation false friends live under a named other programme
(``/vol9/programs/BTK_2019/``) so "lig012" demonstrably belongs to BTK's
numbering, not JAK2's.

What I tried and could not break. ``id_tokens`` strips zeros only inside
one ``[a-z]+\\d+`` run and keeps the letters, so ``cmpd012`` -> ``{cmpd012,
cmpd12}`` never meets ``lig012`` -> ``{lig012, lig12}``, and ``cmpd_012``
yields no token at all: a different prefix cannot collide. The docking-only
sweep cannot become a root without trajectories, however MD-like its other
files are. A folder name alone (graduation 0.5) never reaches the 0.7 pick
threshold. Copies inside the docking folder hash-match only the docking
folder's own raw poses, never a candidate.

What does break (three known gaps, one rule). ``stem_collision``,
``library_beside_unrelated_md`` and ``graduation_false_friend_summary`` all
fail the same way: ``derived`` evidence is collected from *every* curated dir
in the inventory, and the curated-dir test is campaign-relative only in its
time and uid criteria, so any later human folder anywhere whose file names
share an id token with a candidate credits it. Recommended hardening (the
*locality rule*): derived evidence from curated dir ``D`` counts for campaign
``C`` only if ``D`` is local to ``C``, i.e. (a) ``D`` is on ``C``'s volume
(the inventory has no device column, so: the first path component) **and**
lies within ``dirname(C.root)`` (the root's parent, the level whose names the
curated-dir scorer already reads), **or** (b) ``D`` also holds at least one
``copy_out``/``hardlink``/``symlink`` evidence into ``C``. Check against the
grounded positive (``positive_amber_basic.kdr_fep``): its ``fep/analysis`` is
inside the root, so (a) holds and lig029's plots still count. The rule
removes the KDR false picks in ``stem_collision`` (other volume, no hash),
the HSP90 false picks in ``library_beside_unrelated_md`` (same volume, but
``/vol7/library`` is not within ``/vol7/groups/modeling/HSP90_2018``; it
stays non-local even at two levels up) and the derived half of
``graduation_false_friend_summary`` (other volume), leaving 0.5 graduation =
``unknown``. Graduation itself should stay global (reappearing later
*elsewhere* is its point) but must never reach the threshold alone.

Twin for the hardening unit (a *positive*, so not encodable here): take
``stem_collision`` and add to ABL's ``md/analysis`` one real copy of
``KDR_2011/fep/run_lig029/prod006.nc`` (``lig029_kdr_ref.nc``). The folder is
then local to KDR *by evidence* (b) even though it sits under ABL on another
volume. Verdict: KDR picks ``run_lig029`` (copy_out 1.0, hash-unambiguous;
the derived plot corroborates) and ``run_lig033`` (derived 0.7 is
legitimate: whoever copied a KDR trajectory into this folder is demonstrably
working in KDR's vocabulary there, and ABL has no lig033 of its own to
compete for the token); all other KDR candidates not_picked; ABL nothing.
The hardening test should assert both halves: without the copy, zero KDR
picks; with it, exactly {029, 033}.
"""

from __future__ import annotations

import posixpath

from ..inventory import Inventory
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy, workday,
)
from . import register


def _monday(weeks_from_t0: int) -> tuple[int, int]:
    """``(day, workday index)`` of the Monday ``weeks_from_t0`` weeks from ``T0``."""
    return 7 * weeks_from_t0, 5 * weeks_from_t0


def _spec(n: int, uid: int, start: int) -> CampaignSpec:
    """A small Amber ligand campaign: ``run_lig001..n``, 6 x 6 h chunks of 1 GB."""
    return CampaignSpec(engine="amber", n_candidates=n, candidate_fmt="run_lig{:03d}", n_chunks=6,
                        chunk_interval_s=6 * 3600, chunk_size=1_000_000_000, uid=uid, start=start)


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
# 1b. The same library on a volume that does hold an unrelated MD campaign.
# --------------------------------------------------------------------------

HSP90_ROOT = "/vol7/groups/modeling/HSP90_2018/md"
HSP90_SUBMITTER = 2601
HSP90_DAY, _ = _monday(-139)
"""Monday 2018-01-08, when the HSP90 campaign was submitted."""
_, LIB_WD = _monday(-48)
"""Workday index of Monday 2019-10-07, when the library was filed."""


@register(
    kind="negative",
    description="A curated best_papers_final library sits on the same volume as a real HSP90 MD campaign but "
                "three levels away in its own tree, and its later notes are named after a third project's "
                "compounds (PIM1 lig007, lig019) whose tokens collide with HSP90's run_lig###; strongest cue: "
                "tree distance on the same volume, with no hash or link into the campaign.",
    expected=ExpectedOutcome.campaign_no_selection(HSP90_ROOT, [f"run_lig{i:03d}" for i in range(1, 31)]),
    known_gap="derived: derived evidence is taken from every curated dir in the inventory, so PIM1_lig007/lig019 "
              "notes in /vol7/library/best_papers_final credit HSP90's run_lig007/run_lig019; locality rule: "
              "derived counts only from a curated dir on the campaign's volume and within the campaign root's "
              "parent (/vol7/groups/modeling/HSP90_2018), or one that also holds copy/hardlink/symlink "
              "evidence into the campaign",
)
def build_library_beside_unrelated_md() -> Inventory:
    """HSP90 (2018) under ``/vol7/groups/modeling``; a PIM1 reading library (2019) under ``/vol7/library``."""
    tb = TreeBuilder(root="/vol7", uid=LIBRARIAN)
    md_campaign(tb, HSP90_ROOT, _spec(30, HSP90_SUBMITTER, at(HSP90_DAY, 3)))
    d = tb.dir(LIB_ROOT, uid=LIBRARIAN)
    files = (
        ("kinase_review_final.pdf", 900_000),
        ("PIM1_lig007_SAR_review.pdf", 700_000),
        ("PIM1_lig019_binding_notes.txt", 4_200),
        ("approved_medchem_summary.pdf", 650_000),
        ("README.md", 1_200),
    )
    for n, (name, size) in enumerate(files):
        tb.file(posixpath.join(d, name), size=size, mtime=at(workday(LIB_WD + n % 2), 9, 20 * n), uid=LIBRARIAN)
    return tb.build()


# --------------------------------------------------------------------------
# 2. Stem collision across two real MD campaigns on different volumes.
# --------------------------------------------------------------------------

KDR_ROOT = "/vol2/projects/KDR_2011/fep"
ABL_ROOT = "/vol5/archive/ABL_2014/md"

KDR_SUBMITTER = 2101
ABL_SUBMITTER = 2202
ANALYST = 3301

KDR_DAY, _ = _monday(-495)
"""Monday 2011-03-14, when the KDR campaign was submitted."""
ABL_DAY, ABL_WD = _monday(-327)
"""Monday 2014-06-02, when the ABL campaign was submitted (and its workday index)."""

KDR_SPEC = _spec(40, KDR_SUBMITTER, at(KDR_DAY, 3))
"""KDR: 40 ligands run_lig001..040 -- includes lig029 and lig033."""

ABL_SPEC = _spec(20, ABL_SUBMITTER, at(ABL_DAY, 3))
"""ABL: only ligands 1..20 of its med-chem register were simulated (run_lig001..020); lig029 and lig033 are
later ABL register compounds that were never run, and only KDR has candidates by those numbers."""


@register(
    kind="negative",
    description="Two unrelated MD campaigns on different volumes both number ligands run_lig###; ABL's own "
                "2014 analysis folder triages the next ABL register compounds (lig029, lig033, never simulated) "
                "whose numbers exist as candidates only in KDR 2011 on another volume; strongest cue: the "
                "curated folder is on a different volume and holds no copy, link or hash into KDR.",
    expected=ExpectedOutcome(
        campaign_roots=frozenset({KDR_ROOT, ABL_ROOT}),
        picked={KDR_ROOT: frozenset(), ABL_ROOT: frozenset()},
        present={KDR_ROOT: frozenset({"run_lig029", "run_lig033"}), ABL_ROOT: frozenset({"run_lig012"})},
    ),
    known_gap="derived: id-token matching ignores where the curated dir is, so lig029_dock_compare.png and "
              "lig033_next_batch_note.txt in /vol5/archive/ABL_2014/md/analysis credit KDR's run_lig029/"
              "run_lig033 on /vol2; locality rule: derived counts only from a curated dir on the campaign's "
              "volume and within the campaign root's parent, or one that also holds copy/hardlink/symlink "
              "evidence into the campaign",
)
def build_stem_collision() -> Inventory:
    """ABL's analysis/ is real and human-curated but only plans ABL's next batch.

    Nothing here copies, links or hashes into either campaign, so both should report zero picks. The
    ``lig029``/``lig033`` names are ABL register numbers beyond the 20 that ABL simulated; the shared
    ``run_lig###`` vocabulary lets the tokens alone cross to KDR's identically numbered candidates.
    """
    tb = TreeBuilder(root="/")
    md_campaign(tb, KDR_ROOT, KDR_SPEC)
    md_campaign(tb, ABL_ROOT, ABL_SPEC)
    analysis = human_analysis(tb, ABL_ROOT, AnalysisSpec(
        uid=ANALYST, first_workday=ABL_WD + 25, bursts=2, files=("README.md", "notes.txt", "summary.xlsx"),
    ))
    tb.file(posixpath.join(analysis, "lig029_dock_compare.png"), size=52_000, mtime=at(workday(ABL_WD + 26), 11),
            uid=ANALYST)
    tb.file(posixpath.join(analysis, "lig033_next_batch_note.txt"), size=3_500,
            mtime=at(workday(ABL_WD + 27), 9, 30), uid=ANALYST)
    return tb.build()


# --------------------------------------------------------------------------
# 3. Docking poses beside an MD campaign.
# --------------------------------------------------------------------------

EGFR_ROOT = "/vol6/projects/EGFR_2016/md"
EGFR_SUBMITTER = 2301
DOCK_HUMAN = 3302
EGFR_DAY, EGFR_WD = _monday(-227)
"""Monday 2016-05-02, when the EGFR campaign was submitted (and its workday index)."""
EGFR_IDS = [f"run_lig{i:03d}" for i in range(1, 25)]


def _egfr_with_docking(compounds: list[str], finals: dict[str, str]) -> Inventory:
    """EGFR MD campaign plus ``docking/raw_poses`` (one ``.sdf`` per compound) and ``docking/top_poses_final``.

    ``finals`` maps compound -> the derived artifact name written for it in ``top_poses_final``, next to a
    copy of its raw pose; everything in the docking tree is dated weeks after the MD campaign.
    """
    tb = TreeBuilder(root="/vol6")
    md_campaign(tb, EGFR_ROOT, _spec(24, EGFR_SUBMITTER, at(EGFR_DAY, 3)))
    parent = posixpath.dirname(EGFR_ROOT)
    raw = tb.dir(posixpath.join(parent, "docking", "raw_poses"), uid=DOCK_HUMAN)
    for n, cmpd in enumerate(compounds):
        tb.file(posixpath.join(raw, f"{cmpd}.sdf"), size=8_000, mtime=at(workday(EGFR_WD + 20), 9, n), uid=DOCK_HUMAN)
    final = tb.dir(posixpath.join(parent, "docking", "top_poses_final"), uid=DOCK_HUMAN)
    for n, (cmpd, artifact) in enumerate(finals.items()):
        tb.copy(posixpath.join(raw, f"{cmpd}.sdf"), posixpath.join(final, f"{cmpd}_pose1.sdf"),
                mtime=at(workday(EGFR_WD + 22), 11, 5 * n), uid=DOCK_HUMAN)
        tb.file(posixpath.join(final, artifact), size=40_000, mtime=at(workday(EGFR_WD + 22), 14, 5 * n),
                uid=DOCK_HUMAN)
    tb.file(posixpath.join(final, "notes.txt"), size=2_000, mtime=at(workday(EGFR_WD + 23), 10), uid=DOCK_HUMAN)
    return tb.build()


@register(
    kind="negative",
    description="A docking top_poses_final folder beside a real MD campaign curates cmpd#### hits (plots, score "
                "sheets, pose copies) from a 4-digit screening library; strongest cue: the folder's id tokens "
                "(cmpd0417...) share neither prefix nor number with the candidates' run_lig###.",
    expected=ExpectedOutcome.campaign_no_selection(EGFR_ROOT, EGFR_IDS),
)
def build_docking_pose_wrong_ids() -> Inventory:
    """``docking/top_poses_final`` curates cmpd#### docking poses beside an unrelated MD campaign."""
    compounds = ["cmpd0417", "cmpd0533", "cmpd0842", "cmpd1090", "cmpd1204", "cmpd1355"]
    return _egfr_with_docking(compounds, {c: f"{c}_pose1.png" for c in compounds[:4]})


@register(
    kind="negative",
    description="A local docking top_poses_final folder (sibling of the MD root, dated after it) curates "
                "screen compounds cmpd012/018/021 whose numbers equal MD candidates run_lig012/018/021 under a "
                "different prefix; strongest cue: same number, different id prefix (cmpd12 never meets lig12), "
                "and cmpd### is demonstrably the screen's own 40-compound namespace.",
    expected=ExpectedOutcome.campaign_no_selection(EGFR_ROOT, EGFR_IDS),
)
def build_docking_pose_same_numbers() -> Inventory:
    """The docking screen numbers its own compounds cmpd001..cmpd040; its top-3 collide numerically with MD ids."""
    compounds = [f"cmpd{i:03d}" for i in range(1, 41)]
    finals = {"cmpd012": "cmpd012_pose1.png", "cmpd018": "cmpd018_dockscore.csv", "cmpd021": "cmpd021_pose1.png"}
    return _egfr_with_docking(compounds, finals)


# --------------------------------------------------------------------------
# 4. Copy-outs from a docking (non-MD) campaign.
# --------------------------------------------------------------------------

DOCK_ROOT = "/vol8/docking_campaigns/vs_run7"
DOCK_SUBMITTER = 2401
HITS_HUMAN = 3402


@register(
    kind="negative",
    description="A uniform, scheduler-driven docking sweep (dock_run_001..060, each with vina.conf, dock.log and "
                "slurm-<id>.out, i.e. three MD file classes) is genuinely curated -- hits_final copies 4 runs out "
                "by hash -- but has no trajectory at all; strongest cue: no trajectories, so it is a real selection "
                "this MD detector is not built to see (a docking detector would).",
    expected=ExpectedOutcome.no_campaign(),
)
def build_docking_only_campaign() -> Inventory:
    """60 uniform docking run dirs plus a real, hash-verified ``hits_final`` selection of 4."""
    tb = TreeBuilder(root="/vol8", uid=DOCK_SUBMITTER)
    for i in range(1, 61):
        cid = f"dock_run_{i:03d}"
        d = tb.dir(posixpath.join(DOCK_ROOT, cid), uid=DOCK_SUBMITTER)
        base = at(30, 2) + i * 300
        tb.file(posixpath.join(d, "vina.conf"), size=600, mtime=base - 60, uid=DOCK_SUBMITTER,
                content_id=f"{DOCK_ROOT}:boilerplate:vina.conf")
        tb.file(posixpath.join(d, "receptor.pdbqt"), size=40_000, mtime=base, uid=DOCK_SUBMITTER)
        tb.file(posixpath.join(d, "ligand.pdbqt"), size=6_000, mtime=base + 30, uid=DOCK_SUBMITTER)
        tb.file(posixpath.join(d, "out.pdbqt"), size=9_000, mtime=base + 90, uid=DOCK_SUBMITTER)
        tb.file(posixpath.join(d, "dock.log"), size=3_000, mtime=base + 100, uid=DOCK_SUBMITTER)
        tb.file(posixpath.join(d, f"slurm-{5_200_000 + i}.out"), size=1_000, mtime=base + 110, uid=DOCK_SUBMITTER)
    hits = tb.dir(posixpath.join(DOCK_ROOT, "hits_final"), uid=HITS_HUMAN)
    picks = ["dock_run_007", "dock_run_018", "dock_run_033", "dock_run_051"]
    pick_by_copy(tb, campaign_root=DOCK_ROOT, dst_dir=hits, cids=picks, src_name="out.pdbqt",
                 rename="{cid}_out.pdbqt", uid=HITS_HUMAN, mtime=at(workday(45), 10))
    tb.file(posixpath.join(hits, "summary.txt"), size=1_500, mtime=at(workday(45), 10, 30), uid=HITS_HUMAN)
    return tb.build()


# --------------------------------------------------------------------------
# 5. Graduation false friends: name-only coincidence, no link into the campaign.
# --------------------------------------------------------------------------

JAK2_ROOT = "/vol1/projects/JAK2_2013/fep"
JAK2_SUBMITTER = 2501
PROGRAMS_OWNER = 3502
JAK2_DAY, _ = _monday(-387)
"""Monday 2013-04-08, when the JAK2 campaign was submitted."""
_, BTK_WD = _monday(-48)
"""Workday index of Monday 2019-10-07, when the BTK programme folder was set up."""
BTK_SERIES = "/vol9/programs/BTK_2019/lig012_series"
"""A later BTK chemistry programme named after *its own* ligand 12."""
JAK2_IDS = [f"run_lig{i:03d}" for i in range(1, 41)]


def _jak2_with_btk_series(extra: tuple[str, ...] = ()) -> Inventory:
    """JAK2 campaign (2013, no analysis dir) plus a BTK programme folder (2019) on another volume."""
    tb = TreeBuilder(root="/vol1", uid=JAK2_SUBMITTER)
    md_campaign(tb, JAK2_ROOT, _spec(40, JAK2_SUBMITTER, at(JAK2_DAY, 3)))
    programs = tb.dir(BTK_SERIES, uid=PROGRAMS_OWNER)
    for n, name in enumerate(("charter.md", "roadmap.pptx", *extra)):
        tb.file(posixpath.join(programs, name), size=40_000, mtime=at(workday(BTK_WD), 9, 30 * n), uid=PROGRAMS_OWNER)
    return tb.build()


@register(
    kind="negative",
    description="A later BTK programme folder named after its own ligand series (lig012_series, 2019, another "
                "volume) reuses JAK2 candidate id lig012 by coincidence; strongest cue: the folder *name* is the "
                "only link, and graduation (0.5) alone must stay below the pick threshold.",
    expected=ExpectedOutcome.campaign_no_selection(JAK2_ROOT, JAK2_IDS),
)
def build_graduation_false_friend() -> Inventory:
    """A campaign with no analysis dir at all, plus an unrelated later programme folder sharing lig012's name."""
    return _jak2_with_btk_series()


@register(
    kind="negative",
    description="The BTK lig012_series folder also holds lig012_summary.xlsx, so one name coincidence is "
                "counted twice (derived 0.7 + graduation 0.5 = 1.2) with no hash, link or content connection "
                "to JAK2; strongest cue: both signals derive from the same off-volume token.",
    expected=ExpectedOutcome.campaign_no_selection(JAK2_ROOT, JAK2_IDS),
    known_gap="derived: lig012_summary.xlsx in the curated off-volume folder /vol9/programs/BTK_2019/"
              "lig012_series adds 0.7 to the 0.5 graduation from the folder's own name, picking JAK2's "
              "run_lig012 on a coincidence; locality rule: derived counts only from a curated dir on the "
              "campaign's volume and within the campaign root's parent, or one that also holds copy/hardlink/"
              "symlink evidence into the campaign (graduation alone then leaves lig012 unknown)",
)
def build_graduation_false_friend_summary() -> Inventory:
    """As :func:`build_graduation_false_friend` plus ``lig012_summary.xlsx`` inside the programme folder."""
    return _jak2_with_btk_series(("lig012_summary.xlsx",))
