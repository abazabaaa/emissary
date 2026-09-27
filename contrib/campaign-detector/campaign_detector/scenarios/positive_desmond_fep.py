"""Positive variant: a Desmond FEP+ campaign on KDR, October 2012, with graduation.

A modeller (uid 2207) runs 24 ligands, each over 12 lambda windows
(``lambda_0.00``..``lambda_1.00``, 8 chunks per window), under
``/vol6/programs/KDR_2012/fep_plus``. The lambda level must fold into its
ligand: 24 candidates, not 288. A med-chem modeller (uid 3211) writes
``fep_plus/fep_results_final`` a month later with dG plots for three ligands.
In 2013 the programme moves on: ``/vol6/programs/KDR_2013`` gets
``<lig007>_analogs`` (lig 7 graduated *and* has a plot: picked) and
``<lig011>_followup`` (graduation alone, 0.5: ``unknown``).

``/vol6/programs/KDR_2014/KDR-7731_series`` is where lig 11 resurfaced under
a registry number; only an external index (InChIKey -> path) can tell, which
is what ``Hooks.graduation`` is for (see ``tests/test_positive_variants.py``).

Two scenarios share the tree and differ only in how ligands are named:

* ``kdr_fep_plus`` uses ``lig_007``; ``id_tokens`` sees no ``[a-z]+\\d+`` run,
  so neither the plots nor the 2013 directories name a candidate: a known
  ``derived`` (and graduation) gap.
* ``kdr_fep_plus_compact_ids`` uses ``lig007`` and must pass as is.
"""

from __future__ import annotations

import posixpath

from ..inventory import Inventory
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_derived,
    workday,
)
from . import register

WEEK = -414
"""Weeks from ``T0`` to Monday 2012-10-01, when the campaign was submitted."""
WD = 5 * WEEK
"""Workday index of that Monday."""

ROOT = "/vol6/programs/KDR_2012/fep_plus"
"""Campaign root."""
LATER = "/vol6/programs/KDR_2013"
"""The follow-up programme directory (after the campaign)."""
REGISTRY_DIR = "/vol6/programs/KDR_2014/KDR-7731_series"
"""Where ligand 11 resurfaced under a registry id (reachable only via a hook)."""

SUBMITTER = 2207
"""uid that submitted the FEP+ jobs."""
ANALYST = 3211
"""uid of the med-chem modeller who wrote ``fep_results_final``."""

PLOTTED = (7, 15, 19)
"""Ligands with a derived ``<id>_dG.png``."""
GRADUATED = 7
"""Ligand whose id names a 2013 analog-series directory."""
FOLLOWED_UP = 11
"""Ligand with graduation evidence only."""

UNDERSCORE_FMT = "lig_{:03d}"
"""Candidate names of ``kdr_fep_plus``."""
COMPACT_FMT = "lig{:03d}"
"""Candidate names of ``kdr_fep_plus_compact_ids``."""


def spec(candidate_fmt: str) -> CampaignSpec:
    """The campaign: 24 ligands x 12 lambda windows x 8 chunks of 150 MB."""
    return CampaignSpec(
        engine="desmond", n_candidates=24, candidate_fmt=candidate_fmt, inner_fmt="lambda_{:.2f}", n_inner=12,
        n_chunks=8, chunk_interval_s=3 * 3600, chunk_size=150_000_000, uid=SUBMITTER, start=at(7 * WEEK, 4),
        stagger_s=600, boilerplate=("config.cfg",),
    )


def _expected(candidate_fmt: str) -> ExpectedOutcome:
    return ExpectedOutcome.selection(
        ROOT, picked=[candidate_fmt.format(i) for i in PLOTTED], unknown=[candidate_fmt.format(FOLLOWED_UP)],
        rest="not_picked",
    )


def _build(candidate_fmt: str) -> Inventory:
    tb = TreeBuilder(root="/vol6")
    s = spec(candidate_fmt)
    md_campaign(tb, ROOT, s)
    tb.file(posixpath.join(ROOT, "kdr_fep_plus.fmp"), size=250_000, mtime=s.start - 1800, uid=SUBMITTER)
    results = human_analysis(tb, ROOT, AnalysisSpec(
        uid=ANALYST, dirname="fep_results_final", first_workday=WD + 20, bursts=2, burst_gap_days=4,
        files=("fep_plus_summary.xlsx", "KDR_FEP_ranking_v2.pptx", "notes.txt", "pred_vs_exp.csv"),
    ))
    pick_by_derived(tb, dst_dir=results, cids=[candidate_fmt.format(i) for i in PLOTTED], suffix="_dG.png",
                    uid=ANALYST, mtime=at(workday(WD + 21), 13, 30))

    # 2013: the programme moves on; directory names carry the ligand ids.
    for i, what, k in ((GRADUATED, "analogs", 140), (FOLLOWED_UP, "followup", 175)):
        d = tb.dir(posixpath.join(LATER, f"{candidate_fmt.format(i)}_{what}"), uid=ANALYST)
        tb.file(posixpath.join(d, "enumeration.csv"), size=80_000, mtime=at(workday(WD + k), 10), uid=ANALYST)
        tb.file(posixpath.join(d, "docking_scores.xlsx"), size=40_000, mtime=at(workday(WD + k + 2), 15),
                uid=ANALYST)
    tb.file(posixpath.join(REGISTRY_DIR, "series_sar.xlsx"), size=60_000, mtime=at(workday(WD + 330), 11),
            uid=ANALYST)
    return tb.build()


@register(
    kind="positive",
    description="Desmond FEP+ on KDR: 24 lig_### x 12 lambda windows fold to 24 candidates; dG plots pick 3; "
                "2013 dirs graduate lig_007 (also plotted) and lig_011 (graduation only: unknown)",
    expected=_expected(UNDERSCORE_FMT),
    name="kdr_fep_plus",
)
def build_kdr_fep_plus() -> Inventory:
    """KDR FEP+ tree with underscore ids (``lig_007``)."""
    return _build(UNDERSCORE_FMT)


@register(
    kind="positive",
    description="Desmond FEP+ on KDR with joined ids (lig007): lambda windows fold; plots pick 3; "
                "lig007 graduation+plot picked, lig011 graduation only unknown",
    expected=_expected(COMPACT_FMT),
    name="kdr_fep_plus_compact_ids",
)
def build_kdr_fep_plus_compact_ids() -> Inventory:
    """KDR FEP+ tree with joined ids (``lig007``)."""
    return _build(COMPACT_FMT)
