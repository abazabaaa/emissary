"""Grounded positive: an Amber relative-binding FEP campaign on KDR, March 2011.

A modeller (uid 2001) submits 48 ligand runs from one script; two never ran
(lig017, lig033). Weeks later a colleague (uid 3002) analyses the results in
``fep/analysis`` and singles out three ligands in three different ways: a
renamed copy of a trajectory, RMSD/stability plots, and a symlink. A stray
copy of lig005 sits in ``analysis/old`` and must not count as a pick.
"""

from __future__ import annotations

import posixpath

from ..inventory import Inventory
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy,
    pick_by_derived, pick_by_symlink, workday,
)
from . import register

WEEK = -495
"""Weeks from ``T0`` to Monday 2011-03-14, when the campaign was submitted."""
WD = 5 * WEEK
"""Workday index of that Monday (``workday(WD + k)`` is k working days later)."""

ROOT = "/vol3/projects/KDR_2011/fep"
"""Campaign root of the grounded scenario."""

SPEC = CampaignSpec(
    engine="amber", n_candidates=48, candidate_fmt="run_lig{:03d}", n_chunks=20, chunk_interval_s=6 * 3600,
    chunk_size=1_200_000_000, uid=2001, skip=frozenset({17, 33}), start=at(7 * WEEK, 3),
)
"""The campaign: 46 of 48 ligands ran, 20 x 6 h chunks of 1.2 GB each."""

ANALYST = 3002
"""uid of the colleague who curated the results."""


@register(
    kind="positive",
    description="Amber FEP on KDR: 46 ligand runs, analysis/ picks lig012 (copy), lig029 (plots), lig041 (link)",
    expected=ExpectedOutcome.selection(ROOT, picked=["run_lig012", "run_lig029", "run_lig041"], rest="not_picked"),
    name="kdr_fep",
)
def build_kdr_fep() -> Inventory:
    """Build the KDR FEP tree."""
    tb = TreeBuilder(root="/vol3")
    md_campaign(tb, ROOT, SPEC)
    tb.file(posixpath.join(ROOT, "submit_all.sh"), size=1_800, mtime=SPEC.start - 600, uid=SPEC.uid)
    analysis = human_analysis(tb, ROOT, AnalysisSpec(
        uid=ANALYST, first_workday=WD + 15, bursts=3,
        files=("dG_summary_v3.xlsx", "notes.txt", "KDR_FEP_topHits_forMedChem.pptx", "README.md"),
    ))
    pick_by_copy(tb, ROOT, analysis, ["run_lig012"], rename="{id}_bestpose.nc", uid=ANALYST,
                 mtime=at(workday(WD + 16), 14, 30))
    pick_by_derived(tb, analysis, ["run_lig029"], suffix="_rmsd.png", uid=ANALYST, mtime=at(workday(WD + 18), 11))
    pick_by_derived(tb, analysis, ["run_lig029"], suffix="_stable.png", uid=ANALYST, mtime=at(workday(WD + 18), 11, 20))
    pick_by_symlink(tb, analysis, ROOT, ["run_lig041"], src_name="prod020.nc", uid=ANALYST,
                    mtime=at(workday(WD + 21), 15))
    old = tb.dir(posixpath.join(analysis, "old"), uid=ANALYST)
    tb.copy(posixpath.join(ROOT, "run_lig005", "prod010.nc"), posixpath.join(old, "lig005_prod010.nc"),
            uid=ANALYST, mtime=at(workday(WD + 16), 9, 30))
    return tb.build()
