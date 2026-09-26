"""Positive variant: an Amber MD campaign on SRC whose picks are symlinks only.

A modeller (uid 2031) runs 40 ligand-bound SRC systems (``run_lig001``..
``run_lig040``, 16 six-hourly chunks) under ``/vol2/projects/SRC_2012/md``
in February 2012. Three weeks later a colleague (uid 3044) keeps a short
list without copying a byte: ``md/analysis/selected_traj`` holds four
relative symlinks -- two to trajectory chunks, one to a restart file and one
to a whole run directory -- next to ``notes.txt`` and a PyMOL session.
``md/analysis`` itself holds the usual summary files and no picks.

A link to the run directory itself resolves to the candidate path, which the
detector attributes to that candidate like any path below it.
"""

from __future__ import annotations

import posixpath

from ..inventory import Inventory
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_symlink,
    workday,
)
from . import register

WEEK = -448
"""Weeks from ``T0`` to Monday 2012-02-06, when the campaign was submitted."""
WD = 5 * WEEK
"""Workday index of that Monday."""

ROOT = "/vol2/projects/SRC_2012/md"
"""Campaign root."""

SUBMITTER = 2031
"""uid that submitted the runs."""
ANALYST = 3044
"""uid of the colleague who made the symlink short list."""

SPEC = CampaignSpec(
    engine="amber", n_candidates=40, candidate_fmt="run_lig{:03d}", n_chunks=16, chunk_interval_s=6 * 3600,
    chunk_size=1_000_000_000, uid=SUBMITTER, start=at(7 * WEEK, 1),
)
"""The campaign: 40 ligands, 16 x 6 h chunks of 1 GB."""

LINKS = (
    ("run_lig008", "prod016.nc", "{id}_traj"),
    ("run_lig014", "prod012.nc", "{id}_equilibrated.nc"),
    ("run_lig027", "prod.rst7", "{id}_last.rst7"),
)
"""``(candidate, file in its run dir, link name)`` of the file symlinks."""
DIR_LINK = "run_lig033"
"""Candidate linked as a whole directory."""
PICKED = frozenset({*(c for c, _, _ in LINKS), DIR_LINK})
"""Every candidate the short list points at."""


@register(
    kind="positive",
    description="Amber SRC MD, 40 runs: analysis/selected_traj picks 4 by relative symlinks only "
                "(2 chunks, 1 restart, 1 whole run dir)",
    expected=ExpectedOutcome.selection(ROOT, picked=PICKED, rest="not_picked"),
    name="src_md",
)
def build_src_md() -> Inventory:
    """Build the SRC symlink-selection tree."""
    tb = TreeBuilder(root="/vol2")
    md_campaign(tb, ROOT, SPEC)
    tb.file(posixpath.join(ROOT, "submit_all.sh"), size=1_500, mtime=SPEC.start - 600, uid=SUBMITTER)
    analysis = human_analysis(tb, ROOT, AnalysisSpec(
        uid=ANALYST, first_workday=WD + 14, bursts=2,
        files=("rmsd_all_runs.png", "summary.xlsx", "README.md"),
    ))
    selected = tb.dir(posixpath.join(analysis, "selected_traj"), uid=ANALYST)
    for n, (cid, src, name) in enumerate(LINKS):
        pick_by_symlink(tb, dst_dir=selected, campaign_root=ROOT, cids=[cid], src_name=src, link_name=name,
                        uid=ANALYST, mtime=at(workday(WD + 16), 10, 15 * n))
    tb.symlink(posixpath.join(selected, DIR_LINK), posixpath.relpath(posixpath.join(ROOT, DIR_LINK), selected),
               mtime=at(workday(WD + 16), 11), uid=ANALYST)
    tb.file(posixpath.join(selected, "notes.txt"), size=2_200, mtime=at(workday(WD + 16), 11, 20), uid=ANALYST)
    tb.file(posixpath.join(selected, "shortlist_poses.pse"), size=9_500_000, mtime=at(workday(WD + 17), 15),
            uid=ANALYST)
    return tb.build()
