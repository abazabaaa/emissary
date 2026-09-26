"""Positive variant: a GROMACS replicate MD campaign on ABL1, June 2014.

A modeller (uid 2104) runs 30 compounds in triplicate (``rep1``..``rep3``,
12 six-hourly ``.xtc`` chunks per replica) under
``/vol5/projects/ABL1_2014/md``. The replica level must fold into its
compound: 30 candidates, not 90. Weeks later a colleague (uid 3107) works in
``md/analysis``: renamed copies of the second replica's last chunk for three
compounds, a multi-replica RMSD plot for a fourth, and a stray copy of a
fifth parked in ``analysis/old`` (tainted, not a pick).

Two scenarios share the tree and differ only in how compounds are named:

* ``abl_md`` uses ``cmpd_007`` (underscore between letters and digits). The
  detector's ``id_tokens`` only sees ``[a-z]+\\d+`` runs, so the plot
  ``cmpd_017_rmsd_reps.png`` names no candidate: a known ``derived`` gap.
* ``abl_md_compact_ids`` uses ``cmpd007`` and must pass as is.
"""

from __future__ import annotations

import posixpath

from ..inventory import Inventory
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy,
    pick_by_derived, workday,
)
from . import register

WEEK = -327
"""Weeks from ``T0`` to Monday 2014-06-02, when the campaign was submitted."""
WD = 5 * WEEK
"""Workday index of that Monday."""

ROOT = "/vol5/projects/ABL1_2014/md"
"""Campaign root."""

SUBMITTER = 2104
"""uid that submitted the replica runs."""
ANALYST = 3107
"""uid of the colleague who analysed the replicas."""

N_CHUNKS = 12
"""Trajectory chunks per replica (``traj001.xtc``..``traj012.xtc``)."""
COPIED = (4, 12, 23)
"""Compounds whose ``rep2`` final chunk was copied out."""
PLOTTED = 17
"""Compound with a derived multi-replica RMSD plot."""
DISCARDED = 21
"""Compound copied into ``analysis/old`` (tainted)."""

UNDERSCORE_FMT = "cmpd_{:03d}"
"""Candidate names of ``abl_md``."""
COMPACT_FMT = "cmpd{:03d}"
"""Candidate names of ``abl_md_compact_ids``."""


def spec(candidate_fmt: str) -> CampaignSpec:
    """The campaign: 30 compounds x 3 replicas x 12 chunks of 0.9 GB."""
    return CampaignSpec(
        engine="gromacs", n_candidates=30, candidate_fmt=candidate_fmt, inner_fmt="rep{}", n_inner=3,
        n_chunks=N_CHUNKS, chunk_interval_s=6 * 3600, chunk_size=900_000_000, uid=SUBMITTER,
        start=at(7 * WEEK, 2), boilerplate=("md.mdp",),
    )


def _expected(candidate_fmt: str) -> ExpectedOutcome:
    picked = [candidate_fmt.format(i) for i in (*COPIED, PLOTTED)]
    return ExpectedOutcome.selection(ROOT, picked=picked, rest="not_picked")


def _build(candidate_fmt: str) -> Inventory:
    tb = TreeBuilder(root="/vol5")
    s = spec(candidate_fmt)
    md_campaign(tb, ROOT, s)
    tb.file(posixpath.join(ROOT, "submit_replicas.sh"), size=2_400, mtime=s.start - 900, uid=SUBMITTER)
    analysis = human_analysis(tb, ROOT, AnalysisSpec(
        uid=ANALYST, first_workday=WD + 12, bursts=3, burst_gap_days=2,
        files=("rmsd_summary.xlsx", "notes.txt", "ABL_T315I_hits_v2.pptx", "README.md", "cluster_centroids.csv"),
    ))
    last = f"traj{N_CHUNKS:03d}.xtc"
    pick_by_copy(tb, campaign_root=ROOT, dst_dir=analysis, cids=[candidate_fmt.format(i) for i in COPIED],
                 src_name=posixpath.join("rep2", last), rename="{id}_rep2_best.xtc", uid=ANALYST,
                 mtime=at(workday(WD + 13), 14))
    pick_by_derived(tb, dst_dir=analysis, cids=[candidate_fmt.format(PLOTTED)], suffix="_rmsd_reps.png",
                    uid=ANALYST, mtime=at(workday(WD + 15), 11, 10))
    old = tb.dir(posixpath.join(analysis, "old"), uid=ANALYST)
    stray = candidate_fmt.format(DISCARDED)
    tb.copy(posixpath.join(ROOT, stray, "rep1", last), posixpath.join(old, f"{stray}_rep1_{last}"),
            uid=ANALYST, mtime=at(workday(WD + 13), 9, 40))
    return tb.build()


@register(
    kind="positive",
    description="GROMACS ABL1 triplicate MD: 30 cmpd_### x rep1..3 fold to 30 candidates; "
                "picks 3 rep2 copies + 1 plot, old/ copy ignored",
    expected=_expected(UNDERSCORE_FMT),
    known_gap="derived: id_tokens only sees letters immediately followed by digits, so 'cmpd_017' (and the "
              "plot 'cmpd_017_rmsd_reps.png') yields no id token and the plot links to no candidate",
    name="abl_md",
)
def build_abl_md() -> Inventory:
    """ABL1 replicate tree with underscore ids (``cmpd_004``)."""
    return _build(UNDERSCORE_FMT)


@register(
    kind="positive",
    description="GROMACS ABL1 triplicate MD with joined ids (cmpd004): replicas fold, "
                "picks 3 rep2 copies + 1 plot",
    expected=_expected(COMPACT_FMT),
    name="abl_md_compact_ids",
)
def build_abl_md_compact_ids() -> Inventory:
    """ABL1 replicate tree with joined ids (``cmpd004``)."""
    return _build(COMPACT_FMT)
