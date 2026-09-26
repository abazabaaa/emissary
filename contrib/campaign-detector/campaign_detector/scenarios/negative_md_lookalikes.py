"""Negative scenarios: MD file names without a real campaign ("MD look-alikes").

Each scenario reproduces a genuinely MD-shaped directory tree -- templated
names, real topology/input/trajectory/log files, TRAJ bytes present -- that
could fool a detector that only pattern-matches on "lots of MD files here".
Every one of them defeats exactly one gate of ``detect._evaluate_root``
(shared naming template, trajectory byte fraction, uid purity, or plain
candidate count) while keeping every other signal as campaign-like as
possible, so rejecting it takes real reasoning rather than a size or
extension check.
"""

from __future__ import annotations

import posixpath

from ..inventory import Inventory
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy, workday,
)
from . import register

# --------------------------------------------------------------------------
# 1. GROMACS regression-test suite: real MD file classes, no shared template
# --------------------------------------------------------------------------

_UNTAR_UID = 4001
_UNTAR_TIME = at(100, 9, 0)

_COMPLEX_TESTS = (
    "acetonitrilRF", "argon-pme", "field-application", "nbnxn-vsite",
    "polarization-water", "solvation-box", "urea-solvent", "wall-repulsion",
)
_SIMPLE_TESTS = (
    "angle-restraints", "bond-constraints", "coulomb-cutoff",
    "dispersion-correction", "pbc-wrap", "vsite-inversion",
)
_REGTEST_FILES = {
    "conf.gro": 200_000, "topol.top": 50_000, "grompp.mdp": 3_000,
    "reference_s.edr": 300_000, "reference_s.trr": 5_000_000, "reference_s.log": 400_000,
}
"""One reference test's files, sized as large as an honest regression test gets."""


def _regtest_case(tb: TreeBuilder, path: str) -> None:
    for name, size in _REGTEST_FILES.items():
        tb.file(posixpath.join(path, name), size=size, mtime=_UNTAR_TIME, uid=_UNTAR_UID)


@register(
    kind="negative",
    description=(
        "regressiontests-2018/{complex,simple}/<name> untarred in place: real TOPO/INPUT/TRAJ/LOG classes at "
        "honest regression-test sizes, submitted by no one and run by no one -- the strongest cue is that "
        "every test keeps its own descriptive name instead of a shared numbered template (so sibling grouping "
        "never reaches min_candidates), reinforced by every file sharing one bulk-untar timestamp with zero "
        "staggering."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_gromacs_regressiontests() -> Inventory:
    """A GROMACS regression-test tarball extracted in place, never run as a campaign."""
    base = "/data/software/gromacs/regressiontests-2018"
    tb = TreeBuilder(root=base, uid=_UNTAR_UID, mtime=_UNTAR_TIME)
    for name in _COMPLEX_TESTS:
        _regtest_case(tb, posixpath.join(base, "complex", name))
    for name in _SIMPLE_TESTS:
        _regtest_case(tb, posixpath.join(base, "simple", name))
    return tb.build()


# --------------------------------------------------------------------------
# 2. Course materials: templated lessons, real TRAJ bytes, but no submitter
# --------------------------------------------------------------------------

_COURSE_ROOT = "/home/courses/md_course_2015"
_COURSE_FILES = {
    "system.gro": 5_000, "topol.top": 2_000, "md.mdp": 800,
    "traj.xtc": 40_000, "handout.pdf": 2_000,
}
"""Every lesson's kit; the trajectory alone is still >= half the directory's bytes."""
_STUDENT_UIDS = (6101, 6102, 6103, 6104)
"""Four students each bulk-copy the whole course; no single owner remains."""
_COPY_DAYS = (40, 42, 45, 47)


@register(
    kind="negative",
    description=(
        "md_course_2015/lesson01..12: identical templated lesson kits (gro/top/mdp/xtc, trajectory bytes "
        "already over half the directory) copied out whole by four different students on four different days "
        "-- the strongest cue is mixed uid ownership with no dominant submitter (purity 0.25), which is "
        "exactly what tells a shared teaching handout apart from someone's production campaign, since no "
        "compute happened here at all."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_md_course() -> Inventory:
    """A tutorial's lesson directories, bulk-copied out by several students."""
    tb = TreeBuilder(root=_COURSE_ROOT)
    for n in range(12):
        lesson = posixpath.join(_COURSE_ROOT, f"lesson{n + 1:02d}")
        uid = _STUDENT_UIDS[n % len(_STUDENT_UIDS)]
        mtime = at(_COPY_DAYS[n % len(_COPY_DAYS)], 20, 0)
        for name, size in _COURSE_FILES.items():
            tb.file(posixpath.join(lesson, name), size=size, mtime=mtime, uid=uid)
    return tb.build()


# --------------------------------------------------------------------------
# 3. Shipped software examples: templated, one owner, but trajectories tiny
# --------------------------------------------------------------------------

_EXAMPLES_ROOT = "/opt/amber18/examples"
_EXAMPLE_FILES = {
    "complex.prmtop": 90_000, "mdin.in": 800, "mdout.out": 3_000, "traj.nc": 5_000,
}
"""A full TOPO/INPUT/LOG/TRAJ set per example; the demo trajectory is a handful of frames."""
_INSTALL_UID = 0
_INSTALL_TIME = at(-800, 3, 0)
"""The vendor's build timestamp, long before any project existed."""


@register(
    kind="negative",
    description=(
        "amber18/examples/ex01..ex20 as shipped with the package install: one owner, one instant, a full "
        "TOPO/INPUT/TRAJ/LOG set per example just like a real screen -- the strongest cue is that the bundled "
        "demo trajectory is a tiny sliver of each example's bytes (traj_byte_fraction ~0.05, well under half), "
        "because these are illustrative few-frame outputs meant to show the file format, not production runs."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_amber_examples() -> Inventory:
    """A vendored Amber examples tree as shipped, never run by any user."""
    tb = TreeBuilder(root=_EXAMPLES_ROOT, uid=_INSTALL_UID)
    for i in range(1, 21):
        ex = posixpath.join(_EXAMPLES_ROOT, f"ex{i:02d}")
        for name, size in _EXAMPLE_FILES.items():
            tb.file(posixpath.join(ex, name), size=size, mtime=_INSTALL_TIME, uid=_INSTALL_UID)
    return tb.build()


# --------------------------------------------------------------------------
# 4. Failed campaign: templated, one submitter, staggered -- but no TRAJ bytes
# --------------------------------------------------------------------------

_FAILED_ROOT = "/scratch/awad/EGFR_prescreen/runs"
_FAILED_UID = 7003
_FAILED_START = at(200, 9, 0)
_FAILED_STAGGER_S = 720
"""A real `sbatch` loop, twelve minutes apart -- regular submission times."""


@register(
    kind="negative",
    description=(
        "EGFR_prescreen/runs/run_lig001..040: one submitter, a shared numbered template, regular twelve-minute"
        "-apart submissions and a scheduler/topology/input/log set per run just like a real screen -- but every "
        "job errors out immediately and prod001.nc lands at 0 bytes, so the strongest cue is a trajectory-byte "
        "fraction of exactly zero (no MD actually ran) even though a TRAJ-classified file exists in every run."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_failed_screen() -> Inventory:
    """A ligand-screening campaign that was submitted but errored before producing any trajectory."""
    tb = TreeBuilder(root=_FAILED_ROOT, uid=_FAILED_UID)
    for i in range(1, 41):
        run = posixpath.join(_FAILED_ROOT, f"run_lig{i:03d}")
        t = _FAILED_START + (i - 1) * _FAILED_STAGGER_S
        jobid = 5_200_000 + i
        tb.file(posixpath.join(run, "complex.prmtop"), size=4_000_000, mtime=t, uid=_FAILED_UID)
        tb.file(posixpath.join(run, "prod.in"), size=2_048, mtime=t, uid=_FAILED_UID)
        tb.file(posixpath.join(run, f"slurm-{jobid}.out"), size=2_000, mtime=t + 5, uid=_FAILED_UID)
        tb.file(posixpath.join(run, "prod001.out"), size=1_500, mtime=t + 5, uid=_FAILED_UID)
        tb.file(posixpath.join(run, "prod001.nc"), size=0, mtime=t + 5, uid=_FAILED_UID)
    return tb.build()


# --------------------------------------------------------------------------
# 5. One-off run: a real campaign shape but only one candidate
# --------------------------------------------------------------------------

_ONEOFF_ROOT = "/vol4/adhoc/BRD4_probe"
_ONEOFF_SPEC = CampaignSpec(
    engine="amber", n_candidates=1, candidate_fmt="run_lig{:03d}", n_chunks=20, chunk_interval_s=6 * 3600,
    chunk_size=1_200_000_000, uid=8002, start=at(300, 3, 0),
)
_ONEOFF_ANALYST = 8500


@register(
    kind="negative",
    description=(
        "BRD4_probe/run_lig001: a single full 20-chunk Amber run with its own analysis/ copy-out of its best "
        "frame, so every per-run signal (chunk count, MD classes, byte fraction) looks exactly like a real "
        "campaign -- the strongest cue is that there is only one candidate directory, far under "
        "min_candidates, so this is MD that genuinely happened without ever being a campaign."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_oneoff_run() -> Inventory:
    """One researcher's single exploratory run, complete with its own analysis, but too few siblings."""
    tb = TreeBuilder(root=_ONEOFF_ROOT)
    names = md_campaign(tb, _ONEOFF_ROOT, _ONEOFF_SPEC)
    analysis = human_analysis(tb, _ONEOFF_ROOT, AnalysisSpec(
        uid=_ONEOFF_ANALYST, first_workday=45, bursts=1, files=("notes.txt", "bestframe_summary.png"),
    ))
    pick_by_copy(tb, _ONEOFF_ROOT, analysis, names, rename="{id}_bestpose.nc", uid=_ONEOFF_ANALYST,
                mtime=at(workday(46), 14, 0))
    return tb.build()
