"""Negative group B1: machine bulk that isn't MD.

Templated sibling directories, one uid, clockwork mtimes and gigabyte chunk
series are what machines leave behind, not only MD engines. Each scenario is
a real kind of non-MD machine output built as close to the positive
(``positive_amber_basic.kdr_fep``) as it honestly can be: 40-60 templated
members, one submitting uid, regular cadence, and in most scenarios a
colleague's worded, working-hours folder next to it that copies or plots one
or two members, so a false campaign would turn straight into false picks. An
archivist would still say "no MD campaign here". Every scenario fails a
*different* campaign-root gate first:

========================  =====================================================
scenario                  first gate it fails (strongest cue)
========================  =====================================================
``ms_runs``               no MD class at all (``.raw``/``.mzML``)
``log_rotation``          2 classes (INPUT, LOG): the TRAJ-shaped series is LOG
``qm_confsearch``         3 classes (INPUT, LOG, SCHED); ``_trj.xyz`` is not TRAJ
``lidar_station``         TRAJ present (``.nc``) but 0.30 of the bytes (< 0.5)
``roms_ensemble``         none: ``.nc`` ocean ensemble passes every gate (gap)
========================  =====================================================

Adversarial review
------------------
The first draft had five scenarios that failed on only three cues, and three
of them (plate microscopy, ``.sql.gz`` database backups, LC-MS runs) failed
on the same one: no file extension is an MD class, so the modal signature is
empty and the detector never looks further. I kept the strongest of the
three (``ms_runs``, now with a real reviewer folder holding copies, a plot
named after a run and a versioned summary) and replaced the other two with
different cues. The database backups became ``lidar_station``: TRAJ is
present, with three classes, and only the byte share keeps it out. The
microscopy became ``roms_ensemble``: every gate passes. ``log_rotation`` now
copies the positive's shape exactly (48 members, 20 six-hourly chunks of
1.2 GB) with an INPUT file beside the chunks, so its only defence is that
the chunk series is class LOG. The Gaussian scan became an ORCA conformer
search with a per-job ``opt_trj.xyz`` optimisation trajectory. That is a
trajectory in the everyday sense but not an MD class, and it keeps the
class count at the maximum a QM job honestly reaches without TRAJ.

The detector is fooled once. ``roms_ensemble`` is an ocean-model ensemble
whose history files are ``.nc`` (netCDF), the same extension as Amber
trajectories. With ``ocean_*.in``, ``roms.log`` and Slurm output it has four
MD classes, uniformity 1.0, one uid, regular chunks and more than 0.9 of its
bytes in "TRAJ", so it becomes a campaign (engine "amber", confidence 0.93).
A colleague's ``figures/`` folder then turns its two per-member plots into
picks. That is recorded as a ``campaign_root`` known gap. A fix needs
sibling-class context (no TOPO class at all, which no MD engine can run
without) or file contents.

I could not break the other four without making them dishonest. Adding a
TRAJ-class file to ``ms_runs``, ``log_rotation`` or ``qm_confsearch``, or
tipping ``lidar_station``'s bytes towards netCDF, would describe a different
dataset. ``lidar_station`` is deliberately one byte-share away from the
ROMS gap: ``.nc`` alone is not a reliable signal in either direction. Its
sizes were chosen, within what a HALO lidar and Cloudnet produce, so that
the root confidence (0.61) also clears its bar. The TRAJ byte fraction is
the only gate left. The other scenarios fail one gate and then fail the
gates that depend on it: an empty signature also has uniformity 0, and
"no TRAJ" also means no TRAJ bytes. When I forced a campaign root onto
``ms_runs``, ``log_rotation`` and ``qm_confsearch``, each human folder
scored as curated (4-6 of 6) and produced ``copy_out``/``derived``
evidence, so the root gate is the only thing standing between them and
false picks. No scenario is kept out by uid purity, template fraction or
uniformity alone. All are one-uid, fully templated trees, because that is
exactly what makes machine bulk dangerous.
"""

from __future__ import annotations

import posixpath
import time

from ..inventory import Inventory
from ..synth import (
    AnalysisSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, pick_by_copy, pick_by_derived, workday,
)
from . import register

_GB = 1_000_000_000
_MB = 1_000_000


def _ymd(ts: int) -> str:
    """``YYYYMMDD`` of an epoch timestamp (UTC)."""
    return time.strftime("%Y%m%d", time.gmtime(ts))


def _human_dir(tb: TreeBuilder, parent: str, dirname: str, files: tuple[str, ...], *, uid: int, wd: int) -> str:
    """A hand-made folder: one of ``files`` per working day from workday ``wd``, at 10:00."""
    return human_analysis(tb, parent, AnalysisSpec(uid=uid, first_workday=wd, bursts=len(files), burst_gap_days=1,
                                                   dirname=dirname, files=files))


# --------------------------------------------------------------------------
# 1. LC-MS instrument export: no MD class anywhere, genuinely curated.
# --------------------------------------------------------------------------

_MS_UID = 9501
_MS_REVIEWER = 9550
_MS_ROOT = "/vol6/proteomics/plasma_2016/export"
_MS_N = 60
_MS_WD = -1000
"""Workday of the first injection (Monday 2016-11-07)."""


@register(
    kind="negative",
    description=(
        f"LC-MS plasma batch: {_MS_N} injections inj0001..inj{_MS_N:04d} of 2 GB .raw + .mzML every 45 min from "
        "one uid, with a reviewer's selected_runs/ copying three and plotting one; not MD because no file in "
        "any injection has an MD extension (empty class signature)."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_ms_runs() -> Inventory:
    """60 instrument injections plus a real human selection; never an MD class."""
    tb = TreeBuilder(root="/vol6", uid=_MS_UID)
    root = tb.dir(_MS_ROOT, uid=_MS_UID)
    start = at(workday(_MS_WD), 19)
    for i in range(1, _MS_N + 1):
        run = tb.dir(posixpath.join(root, f"inj{i:04d}"), uid=_MS_UID)
        t = start + (i - 1) * 2700
        tb.file(posixpath.join(run, "acquisition.raw"), size=2 * _GB, mtime=t, uid=_MS_UID)
        tb.file(posixpath.join(run, "acquisition.mzML"), size=150 * _MB, mtime=t + 600, uid=_MS_UID)
    selected = _human_dir(tb, root, "selected_runs", ("QC_summary_v2.xlsx", "notes.txt"), uid=_MS_REVIEWER,
                          wd=_MS_WD + 10)
    pick_by_copy(tb, root, selected, ["inj0007", "inj0031", "inj0045"], src_name="acquisition.raw",
                 rename="{cid}.raw", uid=_MS_REVIEWER, mtime=at(workday(_MS_WD + 8), 9, 30))
    pick_by_derived(tb, selected, ["inj0031"], suffix="_tic.png", uid=_MS_REVIEWER,
                    mtime=at(workday(_MS_WD + 9), 14))
    return tb.build()


# --------------------------------------------------------------------------
# 2. Web-tier log archive: a TRAJ-shaped chunk series that is class LOG.
# --------------------------------------------------------------------------

_LOG_UID = 6201
_LOG_ANALYST = 6250
_LOG_ROOT = "/vol4/ops/weblogs/2021Q1"
_LOG_N = 48
_LOG_CHUNKS = 20
_LOG_WD = 85
"""Workday on which the collection window opens (Monday 2021-01-04)."""


@register(
    kind="negative",
    description=(
        f"Web-tier log archive: {_LOG_N} hosts web001..web{_LOG_N:03d}, each with {_LOG_CHUNKS} six-hourly 1.2 GB "
        "access_NNN.log rotations, error.log and nginx.conf from one collector uid, plus an incident folder "
        "copying and plotting web017; not MD because the trajectory-shaped chunk series is class LOG, "
        "leaving 2 classes and no TRAJ."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_log_rotation() -> Inventory:
    """Same member count, chunk count, cadence and chunk size as the positive, but the chunks are logs."""
    tb = TreeBuilder(root="/vol4", uid=_LOG_UID)
    root = tb.dir(_LOG_ROOT, uid=_LOG_UID)
    start = at(workday(_LOG_WD), 3)
    for h in range(1, _LOG_N + 1):
        host = tb.dir(posixpath.join(root, f"web{h:03d}"), uid=_LOG_UID)
        t0 = start + (h - 1) * 900
        tb.file(posixpath.join(host, "nginx.conf"), size=6_144, mtime=t0 - 60, uid=_LOG_UID)
        for k in range(_LOG_CHUNKS):
            tb.file(posixpath.join(host, f"access_{k + 1:03d}.log"), size=1_200 * _MB, mtime=t0 + k * 21600,
                    uid=_LOG_UID)
        tb.file(posixpath.join(host, "error.log"), size=51_200, mtime=t0 + (_LOG_CHUNKS - 1) * 21600, uid=_LOG_UID)
    incident = _human_dir(tb, root, "incident_2021-01", ("postmortem_final.md", "timeline.txt"), uid=_LOG_ANALYST,
                          wd=_LOG_WD + 13)
    pick_by_copy(tb, root, incident, ["web017"], src_name="access_012.log", rename="{cid}_access_012.log",
                 uid=_LOG_ANALYST, mtime=at(workday(_LOG_WD + 12), 11))
    pick_by_derived(tb, incident, ["web017"], suffix="_5xx_rate.png", uid=_LOG_ANALYST,
                    mtime=at(workday(_LOG_WD + 12), 15))
    return tb.build()


# --------------------------------------------------------------------------
# 3. ORCA conformer search: INPUT + LOG + SCHED, per-job .xyz trajectory.
# --------------------------------------------------------------------------

_QM_UID = 8401
_QM_REVIEWER = 8450
_QM_ROOT = "/vol5/qm/BRD4_confsearch_2019/dft_opt"
_QM_N = 60
_QM_WD = -300
"""Workday of the array-job submission (Monday 2019-07-15)."""
_QM_JOBID = 4_400_000
_QM_OUTPUTS = (("opt.gbw", 38 * _MB, 5400), ("opt_trj.xyz", 420_000, 5400), ("opt.xyz", 6_000, 5400),
               ("opt.engrad", 9_000, 5400), ("opt.opt", 40_000, 5400), ("opt.out", 2 * _MB, 5460))
"""ORCA outputs of one geometry optimisation: (name, size, seconds after start)."""


@register(
    kind="negative",
    description=(
        f"ORCA DFT re-optimisation of {_QM_N} CREST conformers conf001..conf{_QM_N:03d} (opt.inp/opt.out/"
        "opt.gbw/opt_trj.xyz/slurm) from one uid every 20 min, with a review/ folder copying two and plotting "
        "one; not MD because the per-job trajectory is an optimisation path in .xyz, so there are 3 classes "
        "and no TRAJ."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_qm_confsearch() -> Inventory:
    """60 QM optimisation jobs; the class count is met, TRAJ never appears."""
    tb = TreeBuilder(root="/vol5", uid=_QM_UID)
    root = tb.dir(_QM_ROOT, uid=_QM_UID)
    start = at(workday(_QM_WD), 18)
    for i in range(1, _QM_N + 1):
        job = tb.dir(posixpath.join(root, f"conf{i:03d}"), uid=_QM_UID)
        t0 = start + (i - 1) * 1200
        tb.file(posixpath.join(job, "opt.inp"), size=2_048, mtime=t0 - 60, uid=_QM_UID)
        tb.file(posixpath.join(job, f"slurm-{_QM_JOBID + i}.out"), size=4_096, mtime=t0 - 60, uid=_QM_UID)
        for name, size, dt in _QM_OUTPUTS:
            tb.file(posixpath.join(job, name), size=size, mtime=t0 + dt, uid=_QM_UID)
    review = _human_dir(tb, root, "review", ("boltzmann_weights_v2.xlsx", "notes.txt"), uid=_QM_REVIEWER,
                        wd=_QM_WD + 8)
    pick_by_copy(tb, root, review, ["conf017", "conf042"], src_name="opt.xyz", rename="{cid}_final.xyz",
                 uid=_QM_REVIEWER, mtime=at(workday(_QM_WD + 6), 10))
    pick_by_derived(tb, review, ["conf017"], suffix="_homo_lumo.png", uid=_QM_REVIEWER,
                    mtime=at(workday(_QM_WD + 7), 14))
    return tb.build()


# --------------------------------------------------------------------------
# 4. Doppler lidar station: .nc (a TRAJ extension) present but a minority.
# --------------------------------------------------------------------------

_LIDAR_UID = 5101
_LIDAR_ROOT = "/data/obs/halo_lidar/2019"
_LIDAR_N = 60
_LIDAR_DAY0 = -556
"""Day number of 2019-03-01 relative to ``T0``."""
_LIDAR_PRODUCTS = (("halo-doppler-lidar", 180 * _MB), ("doppler-lidar-wind", 22 * _MB), ("epsilon-lidar", 60 * _MB))
"""Daily Cloudnet netCDF products: (name prefix, size)."""


@register(
    kind="negative",
    description=(
        f"Doppler lidar station: {_LIDAR_N} daily dirs (YYYYMMDD) of 24 hourly 25 MB .hpl raw scans, "
        "processing.conf, process.log and three daily Cloudnet .nc products from one ingest uid; not MD because "
        "the .nc files are derived netCDF products and raw instrument scans hold about 70% of the bytes."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_lidar_station() -> Inventory:
    """INPUT + LOG + TRAJ-class ``.nc`` per day, but the bytes are raw instrument data."""
    tb = TreeBuilder(root="/data", uid=_LIDAR_UID)
    root = tb.dir(_LIDAR_ROOT, uid=_LIDAR_UID)
    for d in range(_LIDAR_N):
        midnight = at(_LIDAR_DAY0 + d, 0)
        ymd = _ymd(midnight)
        day = tb.dir(posixpath.join(root, ymd), uid=_LIDAR_UID)
        for h in range(24):
            tb.file(posixpath.join(day, f"Stare_46_{ymd}_{h:02d}.hpl"), size=25 * _MB,
                    mtime=midnight + h * 3600 + 3590, uid=_LIDAR_UID)
        done = midnight + 86400 + 1800
        tb.file(posixpath.join(day, "processing.conf"), size=3_000, mtime=done - 60, uid=_LIDAR_UID)
        for n, (prefix, size) in enumerate(_LIDAR_PRODUCTS):
            tb.file(posixpath.join(day, f"{prefix}_{ymd}.nc"), size=size, mtime=done + 60 * n, uid=_LIDAR_UID)
        tb.file(posixpath.join(day, "process.log"), size=40_000, mtime=done + 300, uid=_LIDAR_UID)
    return tb.build()


# --------------------------------------------------------------------------
# 5. ROMS ocean ensemble: netCDF history files pass as MD trajectories.
# --------------------------------------------------------------------------

_ROMS_UID = 7701
_ROMS_ANALYST = 7702
_ROMS_ROOT = "/vol7/ocean/NWA_ensemble_2018/runs"
_ROMS_N = 40
_ROMS_CHUNKS = 12
_ROMS_WD = -600
"""Workday of the ensemble submission (Monday 2018-05-21)."""
_ROMS_JOBID = 5_300_000


@register(
    kind="negative",
    description=(
        f"ROMS ocean ensemble: {_ROMS_N} members mem001..mem{_ROMS_N:03d}, each with ocean_nwa.in, {_ROMS_CHUNKS} "
        "regular 1.5 GB nwa_his_NNNN.nc history chunks, nwa_rst.nc, roms.log and slurm output from one uid, "
        "plus a figures/ folder plotting two members; not MD because it is an ocean model, which only the "
        "missing TOPO class or the file contents can reveal (.nc is also the Amber trajectory extension)."
    ),
    expected=ExpectedOutcome.no_campaign(),
    known_gap=("campaign_root: .nc is ambiguous (netCDF climate/ocean/instrument data vs Amber trajectories); "
               "needs content or sibling-class context such as the absence of any TOPO file"),
)
def build_roms_ensemble() -> Inventory:
    """Campaign-shaped non-MD ensemble whose netCDF output is indistinguishable from TRAJ by extension."""
    tb = TreeBuilder(root="/vol7", uid=_ROMS_UID)
    root = tb.dir(_ROMS_ROOT, uid=_ROMS_UID)
    start = at(workday(_ROMS_WD), 21)
    end = _ROMS_CHUNKS * 14400
    for m in range(1, _ROMS_N + 1):
        mem = tb.dir(posixpath.join(root, f"mem{m:03d}"), uid=_ROMS_UID)
        t0 = start + (m - 1) * 600
        tb.file(posixpath.join(mem, "ocean_nwa.in"), size=60_000, mtime=t0 - 120, uid=_ROMS_UID)
        tb.file(posixpath.join(mem, "varinfo.dat"), size=180_000, mtime=t0 - 120, uid=_ROMS_UID)
        tb.file(posixpath.join(mem, f"slurm-{_ROMS_JOBID + m}.out"), size=30_000, mtime=t0 - 60, uid=_ROMS_UID)
        for k in range(_ROMS_CHUNKS):
            tb.file(posixpath.join(mem, f"nwa_his_{k + 1:04d}.nc"), size=1_500 * _MB, mtime=t0 + (k + 1) * 14400,
                    uid=_ROMS_UID)
        tb.file(posixpath.join(mem, "nwa_rst.nc"), size=900 * _MB, mtime=t0 + end + 60, uid=_ROMS_UID)
        tb.file(posixpath.join(mem, "roms.log"), size=4 * _MB, mtime=t0 + end + 90, uid=_ROMS_UID)
    figures = _human_dir(tb, posixpath.dirname(root), "figures", ("ensemble_spread_v2.pdf", "notes.txt", "README.md"),
                         uid=_ROMS_ANALYST, wd=_ROMS_WD + 11)
    pick_by_derived(tb, figures, ["mem017", "mem029"], suffix="_sst_anomaly.png", uid=_ROMS_ANALYST,
                    mtime=at(workday(_ROMS_WD + 10), 11))
    return tb.build()
