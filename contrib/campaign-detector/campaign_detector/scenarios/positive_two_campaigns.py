"""Positive variant: one project directory holding two campaigns of different engines.

``/vol7/projects/BRD4_2015`` (January 2015) holds an Amber FEP campaign in
``fep/`` (uid 2051, 30 ligands ``run_lig001``..``run_lig030``) and, a week
later, a NAMD apo/holo MD campaign in ``md/`` (uid 2052, 20 systems
``sys_01``..``sys_20``). One shared project-level ``analysis/`` (uid 3060)
holds copy-outs from both campaigns -- two FEP trajectories and one NAMD
trajectory -- and a plot naming lig005 of the FEP campaign. Each campaign must
be its own root and each pick must bind to the campaign it came from.
"""

from __future__ import annotations

import posixpath

from ..inventory import Inventory
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy,
    pick_by_derived, workday,
)
from . import register

WEEK = -295
"""Weeks from ``T0`` to Monday 2015-01-12, when the FEP campaign was submitted."""
WD = 5 * WEEK
"""Workday index of that Monday."""

PROJECT = "/vol7/projects/BRD4_2015"
"""Project directory holding both campaigns."""
FEP_ROOT = f"{PROJECT}/fep"
"""Amber FEP campaign root."""
MD_ROOT = f"{PROJECT}/md"
"""NAMD MD campaign root."""

ANALYST = 3060
"""uid of the modeller who analysed both campaigns."""

FEP_SPEC = CampaignSpec(
    engine="amber", n_candidates=30, candidate_fmt="run_lig{:03d}", n_chunks=12, chunk_interval_s=4 * 3600,
    chunk_size=800_000_000, uid=2051, start=at(7 * WEEK, 3),
)
"""The FEP campaign: 30 ligands, 12 x 4 h chunks."""
MD_SPEC = CampaignSpec(
    engine="namd", n_candidates=20, candidate_fmt="sys_{:02d}", n_chunks=10, chunk_interval_s=8 * 3600,
    chunk_size=1_500_000_000, uid=2052, start=at(7 * WEEK + 7, 5), boilerplate=("prod.inp",),
)
"""The NAMD campaign: 20 systems, 10 x 8 h chunks, one week later."""

FEP_COPIED = ("run_lig009", "run_lig022")
"""FEP candidates copied into ``analysis/``."""
FEP_PLOTTED = "run_lig005"
"""FEP candidate named by a derived plot."""
MD_COPIED = ("sys_13",)
"""NAMD candidates copied into ``analysis/``."""

EXPECTED = ExpectedOutcome(
    campaign_roots=frozenset({FEP_ROOT, MD_ROOT}),
    picked={FEP_ROOT: frozenset({*FEP_COPIED, FEP_PLOTTED}), MD_ROOT: frozenset(MD_COPIED)},
    rest={FEP_ROOT: "not_picked", MD_ROOT: "not_picked"},
)
"""Two roots, each with its own picks; everything else not_picked on both."""


@register(
    kind="positive",
    description="BRD4 project with Amber fep/ (30 ligands) and NAMD md/ (20 systems); shared analysis/ picks "
                "lig009, lig022 (copies), lig005 (plot) in fep and sys_13 (copy) in md",
    expected=EXPECTED,
    name="project_with_two",
)
def build_project_with_two() -> Inventory:
    """Build the two-campaign BRD4 project tree."""
    tb = TreeBuilder(root="/vol7")
    md_campaign(tb, FEP_ROOT, FEP_SPEC)
    md_campaign(tb, MD_ROOT, MD_SPEC)
    tb.file(posixpath.join(FEP_ROOT, "submit_fep.sh"), size=1_700, mtime=FEP_SPEC.start - 600, uid=FEP_SPEC.uid)
    tb.file(posixpath.join(MD_ROOT, "submit_md.sh"), size=1_900, mtime=MD_SPEC.start - 600, uid=MD_SPEC.uid)
    analysis = human_analysis(tb, PROJECT, AnalysisSpec(
        uid=ANALYST, first_workday=WD + 18, bursts=3,
        files=("BRD4_fep_vs_md_v1.xlsx", "notes.txt", "BRD4_update_forMedChem.pptx", "README.md"),
    ))
    pick_by_copy(tb, campaign_root=FEP_ROOT, dst_dir=analysis, cids=FEP_COPIED, src_name="prod012.nc",
                 rename="{id}_fep_endstate.nc", uid=ANALYST, mtime=at(workday(WD + 19), 10, 30))
    pick_by_copy(tb, campaign_root=MD_ROOT, dst_dir=analysis, cids=MD_COPIED, src_name="prod010.dcd",
                 rename="{cid}_holo_final.dcd", uid=ANALYST, mtime=at(workday(WD + 20), 14))
    pick_by_derived(tb, dst_dir=analysis, cids=[FEP_PLOTTED], suffix="_pocket_rmsf.png", uid=ANALYST,
                    mtime=at(workday(WD + 21), 11, 45))
    return tb.build()
