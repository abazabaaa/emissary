"""Positive twins of the hardening rules (unit C1): the other side of every new boundary.

Each hardening rule closes a negative's known gap by rejecting something; the
twin here is the closest honest positive that the same rule must *not*
reject. The twins were described by the adversarial reviewers of groups B3
and B5 (module docstrings of :mod:`negative_copies` and
:mod:`negative_mismatched`) or follow from a rule's own guard:

=================================  ===========================================  =================================
twin                               rule it guards                               negative on the other side
=================================  ===========================================  =================================
``human_shaped_70``                machine-shaped 50-80% band, completed runs   ``negative_copies.coverage_cap_70``
``mirror_snapshot_with_picks``     mirror provenance, derived locality          ``negative_copies.mirror_backup``
``stem_collision_with_copy``       derived locality (b): link evidence          ``negative_mismatched.stem_collision``
``same_account_analysis``          script cadence (owner == submitter)          ``negative_automation.submission_postprocess``
``desmond_trj_fep``                Desmond ``<job>_trj/frame*`` as TRAJ          (none: a real layout, now visible)
=================================  ===========================================  =================================
"""

from __future__ import annotations

import posixpath

from ..inventory import Inventory
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy,
    pick_by_derived, pick_by_symlink, workday,
)
from . import register
from .negative_copies import (
    S1_ANALYST, S1_DAY, S1_PROJECT, S1_ROOT, S1_SPEC, S8B_CRASHED, S8B_CRASHED_SPEC, S8B_SPEC, _cp_p_mirror, _names,
    _s1_project, _wd,
)
from .negative_mismatched import ABL_ROOT, ABL_SPEC, ABL_WD, ANALYST, KDR_ROOT, KDR_SPEC

# --------------------------------------------------------------------------
# 1. The human-shaped 70% copy-out (B3's twin of coverage_cap_70).
# --------------------------------------------------------------------------

H70_PARENT = "/vol6/hts/COVID_2019c"
H70_ROOT = H70_PARENT + "/dock"
H70_SHORTLIST = H70_PARENT + "/shortlist"
H70_ANALYST = 3711
H70_ALL = [f"run_cpd{i:03d}" for i in range(1, 31)]
H70_PICKED_IDX = (3, 10, 17, 24, 27, 30,  # six of the nine crashed runs
                  1, 4, 5, 6, 9, 11, 12, 15, 16, 18, 21, 22, 23, 26, 28)  # 15 of the 21 finished runs
"""21 of 30: not the finished set (six crashed runs in, six finished runs out)."""
H70_ORDER = (22, 4, 17, 9, 30, 1, 12, 27, 5, 18, 3, 26, 11, 24, 6, 21, 15, 10, 28, 16, 23)
"""The order the analyst copied them in: by interest, not by id."""
H70_STYLES = ("{id}_nice_pose.dcd", "{id}_keep_v2.dcd", "{id}_for_MedChem.dcd", "{id}_shortlist.dcd")
"""One rename style per afternoon."""


@register(
    kind="positive",
    description="an analyst copies 21 of 30 runs (six crashed runs in, six finished runs out) into a flat "
                "shortlist/ over four afternoons on different days, out of id order, each renamed by hand, with "
                "notes.txt and ranking.xlsx edited between sessions; strongest cue: human shape at 70% coverage "
                "(several bursts, renames, a set no machine predicate computes)",
    expected=ExpectedOutcome.selection(H70_ROOT, picked=[f"run_cpd{i:03d}" for i in H70_PICKED_IDX],
                                       rest="not_picked"),
)
def build_human_shaped_70() -> Inventory:
    """The ``coverage_cap_70`` campaign (9 of 30 crashed at chunk 6) with a human 70% shortlist."""
    tb = TreeBuilder(root="/vol6")
    md_campaign(tb, H70_ROOT, S8B_SPEC)
    md_campaign(tb, H70_ROOT, S8B_CRASHED_SPEC)
    assert sorted(H70_ORDER) == sorted(H70_PICKED_IDX)
    for n, i in enumerate(H70_ORDER):
        session, slot = divmod(n, 6)
        cid = f"run_cpd{i:03d}"
        src = "prod006.dcd" if i in S8B_CRASHED else "prod010.dcd"
        t = at(_wd(-889, 12 + 3 * session), 14) + slot * 600 + 97 * (n % 7)
        pick_by_copy(tb, H70_ROOT, H70_SHORTLIST, [cid], src_name=src, rename=H70_STYLES[session],
                     uid=H70_ANALYST, mtime=t)
    for session, name in enumerate(("notes.txt", "ranking.xlsx", "notes_v2.txt")):
        tb.file(posixpath.join(H70_SHORTLIST, name), size=6_000, mtime=at(_wd(-889, 13 + 3 * session), 10, 30),
                uid=H70_ANALYST)
    return tb.build()


# --------------------------------------------------------------------------
# 2. A mirror at an untainted path, with real picks in the original (B3's twin of mirror_backup).
# --------------------------------------------------------------------------

SNAPSHOT = "/vol7/snapshots/2012-03/ABT_2012"
MIRROR_PICKS = ("run_lig012", "run_lig019", "run_lig021")


@register(
    kind="positive",
    description="the ABT project's analysis/ picks lig012 (renamed copy), lig019 (plot) and lig021 (relative "
                "symlink), and the whole project is then cp -p'd to an untainted snapshots/ path; strongest cue: "
                "the ctime-earlier original keeps the campaign and its picks, and the mirrored analysis credits "
                "the same candidates (its symlink resolves inside the mirror)",
    expected=ExpectedOutcome.selection(S1_ROOT, picked=MIRROR_PICKS, rest="not_picked"),
)
def build_mirror_snapshot_with_picks() -> Inventory:
    """``negative_copies.mirror_backup`` with three picks, mirrored to ``/vol7/snapshots``."""
    tb = TreeBuilder(root="/vol7")
    analysis = _s1_project(tb)
    pick_by_copy(tb, S1_ROOT, analysis, ["run_lig012"], rename="{id}_bestpose.nc", uid=S1_ANALYST,
                 mtime=at(_wd(S1_DAY, 17), 10))
    pick_by_derived(tb, analysis, ["run_lig019"], suffix="_rmsd.png", uid=S1_ANALYST, mtime=at(_wd(S1_DAY, 17), 14))
    pick_by_symlink(tb, analysis, S1_ROOT, ["run_lig021"], uid=S1_ANALYST, mtime=at(_wd(S1_DAY, 18), 11))
    assert set(MIRROR_PICKS) <= set(_names(S1_SPEC))
    _cp_p_mirror(tb, tb.build(), S1_PROJECT, SNAPSHOT, ctime=at(-3101, 9))
    return tb.build()


# --------------------------------------------------------------------------
# 3. Stem collision plus one real copy into KDR (B5's twin of stem_collision).
# --------------------------------------------------------------------------


@register(
    kind="positive",
    description="stem_collision plus one real copy of KDR run_lig029/prod006.nc in ABL's md/analysis "
                "(lig029_kdr_ref.nc): the folder is local to KDR by evidence, so the copy picks lig029 and the "
                "lig033 note counts as derived; strongest cue: a hash-unambiguous copy into KDR",
    expected=ExpectedOutcome(
        campaign_roots=frozenset({KDR_ROOT, ABL_ROOT}),
        picked={KDR_ROOT: frozenset({"run_lig029", "run_lig033"}), ABL_ROOT: frozenset()},
        rest={KDR_ROOT: "not_picked"},
    ),
)
def build_stem_collision_with_copy() -> Inventory:
    """ABL's analysis triages lig029/lig033 and also holds a copy of KDR's lig029 trajectory."""
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
    pick_by_copy(tb, KDR_ROOT, analysis, ["run_lig029"], src_name="prod006.nc", rename="{id}_kdr_ref.nc",
                 uid=ANALYST, mtime=at(workday(ABL_WD + 26), 14))
    return tb.build()


# --------------------------------------------------------------------------
# 4. The submitter analyses their own campaign by hand (guard of the script-cadence rule).
# --------------------------------------------------------------------------

OWN_ROOT = "/vol4/projects/BTK_2017/md"
OWN_SPEC = CampaignSpec(engine="amber", n_candidates=20, candidate_fmt="run_lig{:03d}", n_chunks=12, uid=2301,
                        start=at(-1100, 3))
OWN_WD = 5 * (-1100 // 7) + 9
"""Two weeks after the campaign ends."""


@register(
    kind="positive",
    description="the modeller who submitted the campaign analyses it under the same uid two weeks later, in "
                "working-hours sessions with notes, a versioned sheet, a renamed copy of lig007 and a plot of "
                "lig015; strongest cue: hand-paced writes long after the last chunk, so the script-cadence veto "
                "(owner == submitter) does not fire",
    expected=ExpectedOutcome.selection(OWN_ROOT, picked=["run_lig007", "run_lig015"], rest="not_picked"),
)
def build_same_account_analysis() -> Inventory:
    tb = TreeBuilder(root="/vol4")
    md_campaign(tb, OWN_ROOT, OWN_SPEC)
    analysis = human_analysis(tb, OWN_ROOT, AnalysisSpec(uid=OWN_SPEC.uid, first_workday=OWN_WD, bursts=2,
                                                         files=("notes.txt", "summary_v2.xlsx", "README.md")))
    pick_by_copy(tb, OWN_ROOT, analysis, ["run_lig007"], rename="{id}_bestpose.nc", uid=OWN_SPEC.uid,
                 mtime=at(workday(OWN_WD + 1), 11, 5))
    pick_by_derived(tb, analysis, ["run_lig015"], suffix="_rmsd.png", uid=OWN_SPEC.uid,
                    mtime=at(workday(OWN_WD + 2), 15, 40))
    return tb.build()


# --------------------------------------------------------------------------
# 5. A Desmond FEP+ campaign in the real on-disk layout.
# --------------------------------------------------------------------------

TRJ_ROOT = "/vol8/programs/PIM1_2016/fep_plus"
TRJ_SPEC = CampaignSpec(
    engine="desmond_trj", n_candidates=16, candidate_fmt="lig{:03d}", inner_fmt="lambda_{:.2f}", n_inner=4,
    n_chunks=8, chunk_interval_s=3 * 3600, chunk_size=150_000_000, uid=2410, start=at(-560, 4), stagger_s=600,
    boilerplate=("md.cfg", "md.msj"),
)
"""16 ligands x 4 lambda windows, each ``md-in.cms``, ``md.msj``, ``md.cfg``, ``md_trj/frame001..008``,
``md_trj/clickme.dtr``, ``md-out.cms``, ``md.ene``, ``md.log``, ``md.cpt`` and ``job.o<id>``."""
TRJ_ANALYST = 3412
TRJ_WD = 5 * (-560 // 7) + 12


@register(
    kind="positive",
    description="Desmond FEP+ in the real layout (md-in.cms/md-out.cms, .msj, .ene and md_trj/ directories "
                "of extension-less frame### files) under 4 lambda windows per ligand; the analyst plots lig004 "
                "and lig011 and symlinks lig009's lambda_0.00/md_trj; strongest cue: md_trj/frame* is the "
                "trajectory and folds into its run",
    expected=ExpectedOutcome.selection(TRJ_ROOT, picked=["lig004", "lig009", "lig011"], rest="not_picked"),
)
def build_desmond_trj_fep() -> Inventory:
    tb = TreeBuilder(root="/vol8")
    md_campaign(tb, TRJ_ROOT, TRJ_SPEC)
    results = human_analysis(tb, TRJ_ROOT, AnalysisSpec(
        uid=TRJ_ANALYST, dirname="fep_results_final", first_workday=TRJ_WD, bursts=2,
        files=("fep_summary.xlsx", "PIM1_ranking_v2.pptx", "notes.txt"),
    ))
    pick_by_derived(tb, results, ["lig004", "lig011"], suffix="_dG.png", uid=TRJ_ANALYST,
                    mtime=at(workday(TRJ_WD + 1), 13, 30))
    pick_by_symlink(tb, results, TRJ_ROOT, ["lig009"], src_name="lambda_0.00/md_trj", link_name="{id}_lambda0",
                    uid=TRJ_ANALYST, mtime=at(workday(TRJ_WD + 2), 10))
    return tb.build()
