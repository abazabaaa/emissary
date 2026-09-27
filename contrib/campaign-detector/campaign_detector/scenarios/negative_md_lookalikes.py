"""Negative scenarios: MD file names without a real campaign ("MD look-alikes").

Each scenario reproduces a genuinely MD-shaped tree (templated names, real
topology/input/trajectory/log files, trajectory bytes present) that an
archivist would still say holds no MD campaign, because nothing was computed
there as a campaign: a regression-test tarball, a teaching course, vendor
examples, a screen that crashed, and a handful of ad-hoc runs. Each is pushed
as close to ``positive_amber_basic.kdr_fep`` as it honestly goes, so rejecting
it needs a specific cue rather than a size or extension check.

Where each one stops in ``detect._evaluate_root`` (values from the default
``Params``; "conf" is the confidence the root would score if the named gate
were absent):

==========================  ======================================  =========================================
scenario                    gate that rejects it                    everything else
==========================  ======================================  =========================================
gromacs_regressiontests     template fraction 0.27 < 0.6 and |G| 3  traj 0.84, purity 1.0, conf 0.75
md_course                   uid purity 0.83 < 0.9                   traj 0.67, uniformity 1.0, conf 0.69
md_course_single_student    none (known gap)                        traj 0.67, purity 1.0, conf 0.72
amber_examples              traj byte fraction 0.43 < 0.5           purity 1.0, 5 MD classes, conf 0.70
failed_screen               traj byte fraction 0.0 < 0.5            purity 1.0, 5 MD classes, conf 0.62
failed_screen_partial       none (known gap)                        traj 0.62, purity 1.0, conf 0.74
oneoff_run                  |G| 3 < 4 (template fraction 0.75 ok)   4 child dirs, full 20-chunk runs
==========================  ======================================  =========================================

Adversarial review. The writer's five scenarios all passed, but two claims in
their summary did not hold and three scenarios stopped short of the hardest
honest point. (1) ``amber_examples`` and ``md_course`` were also below the 0.6
confidence floor (0.593 and 0.598), so neither was "blocked by exactly one
gate". ``amber_examples`` now ships what a vendor example really needs --
starting coordinates, a reference restart and a 20-frame demo trajectory of a
30k-atom solvated complex -- which lifts its trajectory fraction from 0.05 to
0.43 and makes the byte gate its sole blocker; at 27 or more frames per example
(or for a small solute-only system) the gate flips and it becomes the same
bulk-copy gap as ``md_course_single_student``, which is why no second variant
was added. (2) ``md_course`` claimed "four students copied the whole course",
which cannot produce one directory whose lessons have four owners; it is now a
course written by a lead instructor (10 lessons) and two guest lecturers (1
each), purity 0.83 -- the most single-authored course the gate still rejects --
with realistic tutorial sizes (a 4 MB reference trajectory per lesson). (3) The
single-uid question: one student's ``cp -r`` of the same course has purity 1.0
and passes every gate, although nothing was computed (every file carries the
copy instant, no chunk series, 4 MB illustrative trajectories). It is kept as
``md_course_single_student`` with a ``campaign_root`` known gap. (4) Failed
screens: the zero-byte ``failed_screen`` is kept, but a screen whose jobs die
1.5-2.5 minutes into their first chunk (4.95-8.25 MB each) passes every gate
because the trajectory fraction is relative to a tree that is itself tiny; that
is ``failed_screen_partial`` with a known gap. (5) ``oneoff_run`` had one run,
so its parent never reached the four-child-dir check; it now has three full
20-chunk runs plus an analysis dir (4 child dirs), rejected only because the
template group is 3 -- an archivist could call three runs a small campaign, but
the detector's stated minimum is 4 and the expectation follows it.
``gromacs_regressiontests`` gained three water-model tests whose names share a
digit template (``tip#p-water``), the largest honest collision; a fourth would
need a fabricated test and would still fail template fraction (4/12). Measured
flip points (each run against the detector, not reasoned): regression tests
with 20 MB reference trajectories stay rejected (the template gate does not
care about bytes); a course with only one guest lesson in twelve (purity 0.92)
is detected, i.e. it collapses into the single-student gap, so ``md_course``
uses two guests; vendor examples flip at 27 frames per 30k-atom example, and a
small solute (alanine dipeptide, 100 frames) flips as well; the partial screen
flips at ~4.01 MB of frames per run (the prmtop plus logs weigh 4.01 MB; its
runs write 4.95-8.25 MB), and adding the ~3 MB restart a crash at a checkpoint
leaves pushes it back under 0.5 (0.46), which is luck of file sizes, not
understanding; three ad-hoc runs become a campaign at four, as the stated
minimum says they should. Variety: ``amber_examples`` and ``failed_screen``
meet at the same detector gate from opposite evidence (a small but real
illustrative trajectory near the threshold versus a file that exists with zero
bytes, which fools any extension count). ``gromacs_regressiontests`` and
``oneoff_run`` both have a template group of 3, but only the regression tests
also fail template fraction (descriptive names), while the ad-hoc runs are
perfectly templated and fail on count alone. The two known gaps name different
missing signals (per-run timestamps for a bulk copy, trajectory volume or
duration for a crash). ``oneoff_run`` also had its analysis dated ~230 days
before its runs; it now follows them by six weeks.
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
    "tip3p-water", "tip4p-water", "tip5p-water",
)
"""Descriptive test names; the three water-model tests share the template ``tip#p-water``."""
_SIMPLE_TESTS = (
    "angle-restraints", "bond-constraints", "coulomb-cutoff",
    "dispersion-correction", "pbc-wrap", "vsite-inversion",
)
_REGTEST_FILES = {
    "conf.gro": 200_000, "topol.top": 50_000, "grompp.mdp": 3_000,
    "reference_s.edr": 300_000, "reference_s.trr": 5_000_000, "reference_s.log": 400_000,
}
"""One reference test's files, sized as large as an honest regression test gets."""


@register(
    kind="negative",
    description=(
        "A GROMACS regressiontests tarball unpacked in place is reference data that nobody submitted, and its "
        "strongest cue is that every test keeps its own descriptive name (the largest shared digit template, "
        "tip3p/4p/5p-water, covers 3 of 11 tests: template fraction 0.27 < 0.6 and |G| < 4) although "
        "trajectory bytes (0.84), uid purity and MD classes all look like a campaign."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_gromacs_regressiontests() -> Inventory:
    """A GROMACS regression-test tarball extracted in place, never run as a campaign."""
    base = "/data/software/gromacs/regressiontests-2018"
    tb = TreeBuilder(root=base, uid=_UNTAR_UID, mtime=_UNTAR_TIME)
    for group, names in (("complex", _COMPLEX_TESTS), ("simple", _SIMPLE_TESTS)):
        for name in names:
            for fname, size in _REGTEST_FILES.items():
                tb.file(posixpath.join(base, group, name, fname), size=size, mtime=_UNTAR_TIME, uid=_UNTAR_UID)
    return tb.build()


# --------------------------------------------------------------------------
# 2-3. Course materials: templated lesson kits with real TRAJ bytes
# --------------------------------------------------------------------------

_COURSE_ROOT = "/home/courses/md_course_2015"
_N_LESSONS = 12
_COURSE_KIT = {
    "system.gro": 1_100_000, "topol.top": 450_000, "md.mdp": 1_200,
    "traj.xtc": 4_000_000, "md.log": 35_000, "handout.pdf": 400_000,
}
"""One lesson's kit: a solvated small protein, a precomputed 4 MB reference
trajectory for the analysis exercises, its log and the handout (traj 0.67 of
the bytes)."""
_LEAD_UID = 6101
_GUEST_UIDS = {5: 6102, 9: 6103}
"""Lesson index (0-based) -> guest lecturer uid; the lead instructor wrote the rest."""


def _course_kit(tb: TreeBuilder, lesson: str, *, uid: int, mtime: int, step_s: int) -> None:
    for j, (name, size) in enumerate(_COURSE_KIT.items()):
        tb.file(posixpath.join(lesson, name), size=size, mtime=mtime + j * step_s, uid=uid)


@register(
    kind="negative",
    description=(
        "md_course_2015/lesson01..12 is a teaching handout, not a production run, and its strongest cue is "
        "authorship: a lead instructor wrote ten lessons and two guest lecturers one each, so uid purity is "
        "0.83 < 0.9 even though the kits are perfectly templated and a 4 MB reference trajectory makes up two "
        "thirds of every lesson's bytes."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_md_course() -> Inventory:
    """A shared course directory whose lessons were written by three people over several weeks."""
    tb = TreeBuilder(root=_COURSE_ROOT, uid=_LEAD_UID)
    for n in range(_N_LESSONS):
        uid = _GUEST_UIDS.get(n, _LEAD_UID)
        _course_kit(tb, posixpath.join(_COURSE_ROOT, f"lesson{n + 1:02d}"), uid=uid,
                    mtime=at(workday(30 + 2 * n), 10), step_s=1_500)
    return tb.build()


_STUDENT_UID = 6205
_STUDENT_COPY = "/home/mchen/md_course_2015"
_COPY_TIME = at(97, 21, 14)


@register(
    kind="negative",
    description=(
        "One student's `cp -r` of the whole course into their home holds no computation at all, and its "
        "strongest cue is time: all 72 files carry the copy instant (one second apart), with a single "
        "illustrative trajectory per lesson and no chunk series, which the detector cannot see because a "
        "single owner, perfect templating and 0.67 trajectory bytes clear every gate."
    ),
    expected=ExpectedOutcome.no_campaign(),
    known_gap=(
        "campaign_root: one-uid bulk copy of course kits with real TRAJ bytes passes every gate; needs a "
        "compute-happened signal (chunk cadence, log size, per-run timestamps)"
    ),
)
def build_md_course_single_student() -> Inventory:
    """The same course kits, copied once by one student; the original course is not on this volume."""
    tb = TreeBuilder(root=_STUDENT_COPY, uid=_STUDENT_UID)
    for n in range(_N_LESSONS):
        _course_kit(tb, posixpath.join(_STUDENT_COPY, f"lesson{n + 1:02d}"), uid=_STUDENT_UID,
                    mtime=_COPY_TIME + n * len(_COURSE_KIT), step_s=1)
    return tb.build()


# --------------------------------------------------------------------------
# 4. Shipped software examples: templated, one owner, few-frame trajectories
# --------------------------------------------------------------------------

_EXAMPLES_ROOT = "/opt/amber18/examples"
_EXAMPLE_FILES = {
    "complex.prmtop": 5_200_000, "complex.inpcrd": 2_200_000, "mdin.in": 1_200,
    "mdout.out": 60_000, "mdcrd.nc": 7_200_000, "restrt.rst7": 2_200_000,
}
"""A runnable example of a 30k-atom solvated complex: topology, starting
coordinates, input, and reference outputs including a 20-frame demo trajectory
(20 x 360 kB; 27+ frames would flip the 0.5 byte gate)."""
_INSTALL_UID = 0
_INSTALL_TIME = at(-800, 3, 0)
"""The vendor's build timestamp, preserved by the install, long before any project existed."""


@register(
    kind="negative",
    description=(
        "amber18/examples/ex01..ex20 as installed by root are vendor reference outputs, and their strongest cue "
        "is that each demo trajectory is a 20-frame illustration smaller than the topology, coordinates and "
        "restart shipped beside it (trajectory fraction 0.43 < 0.5), although names, owner and five MD classes "
        "match a real screen."
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
# 5-6. Failed screens: templated, one submitter, staggered starts
# --------------------------------------------------------------------------

_FAILED_ROOT = "/scratch/awad/EGFR_prescreen/runs"
_FAILED_UID = 7003
_FAILED_START = at(200, 9, 0)
_FAILED_STAGGER_S = 720
"""Jobs start twelve minutes apart as nodes free up -- a real, regular submission cadence."""
_N_FAILED = 40


def _failed_run(tb: TreeBuilder, root: str, i: int, *, died_after_s: int, traj_bytes: int, out_bytes: int) -> None:
    run = posixpath.join(root, f"run_lig{i:03d}")
    t = _FAILED_START + (i - 1) * _FAILED_STAGGER_S
    tb.file(posixpath.join(run, "complex.prmtop"), size=4_000_000, mtime=t - 60, uid=_FAILED_UID)
    tb.file(posixpath.join(run, "prod.in"), size=2_048, mtime=t - 60, uid=_FAILED_UID,
            content_id=f"{root}:boilerplate:prod.in")
    tb.file(posixpath.join(run, f"slurm-{5_200_000 + i}.out"), size=2_000, mtime=t + died_after_s, uid=_FAILED_UID)
    tb.file(posixpath.join(run, "prod001.out"), size=out_bytes, mtime=t + died_after_s, uid=_FAILED_UID)
    tb.file(posixpath.join(run, "prod001.nc"), size=traj_bytes, mtime=t + died_after_s, uid=_FAILED_UID)


@register(
    kind="negative",
    description=(
        "EGFR_prescreen/runs/run_lig001..040 was submitted by one user on a regular cadence but every job died "
        "at step 0, and the strongest cue is that each prod001.nc exists with zero bytes, so a TRAJ file is in "
        "every run while the trajectory byte fraction is exactly 0."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_failed_screen() -> Inventory:
    """A ligand screen that was submitted but errored before producing any trajectory."""
    tb = TreeBuilder(root=_FAILED_ROOT, uid=_FAILED_UID)
    for i in range(1, _N_FAILED + 1):
        _failed_run(tb, _FAILED_ROOT, i, died_after_s=5, traj_bytes=0, out_bytes=1_500)
    return tb.build()


_PARTIAL_ROOT = "/scratch/awad/EGFR_prescreen_v2/runs"


@register(
    kind="negative",
    description=(
        "The resubmitted screen crashed about two minutes into every first chunk (a few MB of frames, no "
        "restart, no second chunk), which an archivist calls a failed launch rather than a campaign, and the "
        "strongest cue is volume and duration: one short chunk per run against the 20 x 6 h a real screen "
        "writes, invisible to a byte fraction measured on a tree that is itself tiny (0.62)."
    ),
    expected=ExpectedOutcome.no_campaign(),
    known_gap=(
        "campaign_root: runs that crash minutes into their first chunk pass every gate because "
        "traj_byte_fraction is relative to an equally tiny tree; needs an absolute trajectory volume or "
        "run-duration floor (chunks per run, t_end - t_start)"
    ),
)
def build_failed_screen_partial() -> Inventory:
    """A ligand screen whose jobs each wrote a few MB of trajectory and then crashed."""
    tb = TreeBuilder(root=_PARTIAL_ROOT, uid=_FAILED_UID)
    for i in range(1, _N_FAILED + 1):
        # 1.2 GB per 6 h chunk is ~3.3 MB per minute; crashes land between 1.5 and 2.5 minutes in.
        died = 90 + (i % 5) * 15
        _failed_run(tb, _PARTIAL_ROOT, i, died_after_s=died, traj_bytes=died * 55_000, out_bytes=9_000)
    return tb.build()


# --------------------------------------------------------------------------
# 7. A few ad-hoc runs: a real campaign shape but only three candidates
# --------------------------------------------------------------------------

_ONEOFF_ROOT = "/vol4/adhoc/BRD4_probe"
_ONEOFF_SPEC = CampaignSpec(
    engine="amber", n_candidates=3, candidate_fmt="run_lig{:03d}", n_chunks=20, chunk_interval_s=6 * 3600,
    chunk_size=1_200_000_000, uid=8002, start=at(300, 3, 0), stagger_s=2 * 86400,
)
"""Three full production runs started two days apart by hand."""
_ONEOFF_ANALYST = 8500
_ONEOFF_ANALYSIS_WD = 250
"""Monday 2021-08-23, six weeks after the last run's final chunk (2021-07-12)."""


@register(
    kind="negative",
    description=(
        "BRD4_probe/run_lig001..003 are three complete 20-chunk Amber runs with their own analysis/ copy-out, "
        "which an archivist might call a small campaign, but the detector's stated minimum is four candidates "
        "and the strongest cue is that count: the parent does reach four child dirs, yet the template group is "
        "only three."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_oneoff_run() -> Inventory:
    """Three exploratory runs of one probe, complete with an analysis dir, but too few siblings."""
    tb = TreeBuilder(root=_ONEOFF_ROOT)
    names = md_campaign(tb, _ONEOFF_ROOT, _ONEOFF_SPEC)
    analysis = human_analysis(tb, _ONEOFF_ROOT, AnalysisSpec(
        uid=_ONEOFF_ANALYST, first_workday=_ONEOFF_ANALYSIS_WD, bursts=2,
        files=("notes.txt", "rmsd_compare_v2.png", "summary.xlsx"),
    ))
    pick_by_copy(tb, _ONEOFF_ROOT, analysis, names[1:2], rename="{id}_bestpose.nc", uid=_ONEOFF_ANALYST,
                 mtime=at(workday(_ONEOFF_ANALYSIS_WD + 1), 14, 0))
    return tb.build()
