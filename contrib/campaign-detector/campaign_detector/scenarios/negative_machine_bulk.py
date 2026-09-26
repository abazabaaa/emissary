"""Negative group B1: machine bulk that isn't MD.

Regular, numbered, single-uid, evenly-timed directory trees are necessary but
not sufficient evidence of an MD campaign: the detector also requires enough
distinct MD file classes, one of which must be TRAJ, dominating the bytes.
Each scenario here is built to be as campaign-shaped as honestly possible
along every axis *except* the one it is testing, so that the sole reason the
detector should refuse it is the stated cue, not sloppy synthesis:

* ``microscopy`` / ``ms_runs`` -- no extension is ever an MD class at all.
* ``log_rotation`` -- one MD-adjacent class (LOG) is present, but that alone
  is short of ``min_md_classes`` and there is no TRAJ.
* ``db_backups`` -- large, evenly spaced, numbered binary blobs mimic a
  trajectory chunk series in size and cadence, but the extension is never
  recognised so no class -- let alone TRAJ -- is ever assigned.
* ``qm_jobs`` -- LOG, RESTART and SCHED are *all* present (meeting the class
  *count* threshold) and a human even curates two jobs afterwards, yet TRAJ
  is still absent, which is exactly the case the detector's explicit
  ``"TRAJ" not in classes`` check exists for.

None of these trees should yield a detected campaign root, so none of their
human-looking directories (``review``, ``selected_runs``) should ever be
reached by curation or evidence collection either.
"""

from __future__ import annotations

import posixpath

from ..inventory import Inventory
from ..synth import ExpectedOutcome, TreeBuilder, at, pick_by_copy
from . import register

# --------------------------------------------------------------------------
# 1. Microscopy image series: per-well, no MD classes at all.
# --------------------------------------------------------------------------

_MICROSCOPY_UID = 5101
_MICROSCOPY_ROOT = "/data/imaging/plate07"
_N_WELLS = 48
_N_IMAGES = 20


@register(
    kind="negative",
    description=(
        "Automated plate scan: 48 templated well_### dirs of 20 evenly spaced img_####.tif frames from one "
        "uid -- perfectly campaign-shaped, but no extension anywhere is an MD class."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_microscopy() -> Inventory:
    """48 numbered wells x 20 timestamped .tif frames; regular, single-uid, never MD."""
    tb = TreeBuilder(root="/data", uid=_MICROSCOPY_UID)
    root = tb.dir(_MICROSCOPY_ROOT, uid=_MICROSCOPY_UID)
    for w in range(1, _N_WELLS + 1):
        well = tb.dir(posixpath.join(root, f"well_{w:03d}"), uid=_MICROSCOPY_UID)
        base = at(300, 6) + w * 1800
        for i in range(1, _N_IMAGES + 1):
            tb.file(posixpath.join(well, f"img_{i:04d}.tif"), size=4_200_000, mtime=base + i * 300,
                    uid=_MICROSCOPY_UID)
    return tb.build()


# --------------------------------------------------------------------------
# 2. Log rotation / monitoring: one MD-adjacent class, nowhere near enough.
# --------------------------------------------------------------------------

_LOG_UID = 6201
_LOG_ROOT = "/vol4/ops/logs/appcluster"
_N_DAYS = 60
_N_METRICS = 12
_N_ERRORS = 4


@register(
    kind="negative",
    description=(
        "Log rotation: 60 templated day_#### dirs, each with hourly metrics_####.log and error_####.log from "
        "one uid, regular as clockwork -- every file is class LOG, so the campaign never reaches 3 MD classes "
        "or a TRAJ file."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_log_rotation() -> Inventory:
    """60 numbered day dirs of .log-only files; one MD class present, min_md_classes and TRAJ both fail."""
    tb = TreeBuilder(root="/vol4", uid=_LOG_UID)
    root = tb.dir(_LOG_ROOT, uid=_LOG_UID)
    for d in range(1, _N_DAYS + 1):
        day = tb.dir(posixpath.join(root, f"day_{d:04d}"), uid=_LOG_UID)
        base = at(500 + d, 0)
        for h in range(1, _N_METRICS + 1):
            tb.file(posixpath.join(day, f"metrics_{h:04d}.log"), size=51_200, mtime=base + h * 3600, uid=_LOG_UID)
        for e in range(1, _N_ERRORS + 1):
            tb.file(posixpath.join(day, f"error_{e:04d}.log"), size=8_192, mtime=base + 21_600 + e * 900,
                    uid=_LOG_UID)
    return tb.build()


# --------------------------------------------------------------------------
# 3. Nightly database backups: TRAJ-sized, TRAJ-timed, but wrong extension.
# --------------------------------------------------------------------------

_DB_UID = 7301
_DB_ROOT = "/vol2/backups/prod_cluster"
_N_NIGHTS = 60
_DB_TABLES = ("customers", "orders", "inventory", "audit")


@register(
    kind="negative",
    description=(
        "Nightly backups: 60 templated backup_#### dirs, each with the same four large .sql.gz dumps on an "
        "evenly spaced 24 h cadence from one uid -- trajectory-chunk sized and timed, but .sql.gz is never an "
        "MD extension so no class is ever assigned."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_db_backups() -> Inventory:
    """60 nightly dirs of uniform large .sql.gz dumps; mimics TRAJ cadence/size, never classifies as MD."""
    tb = TreeBuilder(root="/vol2", uid=_DB_UID)
    root = tb.dir(_DB_ROOT, uid=_DB_UID)
    for n in range(1, _N_NIGHTS + 1):
        night = tb.dir(posixpath.join(root, f"backup_{n:04d}"), uid=_DB_UID)
        base = at(600 + n, 2)
        for t_i, table in enumerate(_DB_TABLES):
            size = 900_000_000 if table == "customers" else 250_000_000
            tb.file(posixpath.join(night, f"{table}.sql.gz"), size=size, mtime=base + t_i * 300, uid=_DB_UID)
    return tb.build()


# --------------------------------------------------------------------------
# 4. Gaussian QM scan: LOG + RESTART + SCHED present, TRAJ absent.
# --------------------------------------------------------------------------

_QM_UID = 8401
_REVIEW_UID = 8450
_QM_ROOT = "/vol5/qm/gaussian_scan"
_N_JOBS = 60
_QM_JOBID_BASE = 4_400_000


@register(
    kind="negative",
    description=(
        "Gaussian QM scan: 60 templated job_### dirs, each with input.com/output.log/checkpoint.chk/"
        "slurm-*.out from one uid at regular submission intervals, plus a human review/ that copies two "
        "jobs' logs -- LOG, RESTART and SCHED all appear (3 classes) but TRAJ never does, so it is not MD."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_qm_jobs() -> Inventory:
    """60 templated QM job dirs meeting the class-count bar via LOG/RESTART/SCHED, but with no TRAJ class."""
    tb = TreeBuilder(root="/vol5", uid=_QM_UID)
    root = tb.dir(_QM_ROOT, uid=_QM_UID)
    for i in range(1, _N_JOBS + 1):
        job = tb.dir(posixpath.join(root, f"job_{i:03d}"), uid=_QM_UID)
        t0 = at(700, 8) + i * 1800
        jobid = _QM_JOBID_BASE + i
        tb.file(posixpath.join(job, "input.com"), size=4_096, mtime=t0 - 300, uid=_QM_UID)
        tb.file(posixpath.join(job, "checkpoint.chk"), size=6_000_000, mtime=t0 + 1800, uid=_QM_UID)
        tb.file(posixpath.join(job, "output.log"), size=180_000, mtime=t0 + 3600, uid=_QM_UID)
        tb.file(posixpath.join(job, f"slurm-{jobid}.out"), size=12_000, mtime=t0 + 3600, uid=_QM_UID)
    review = tb.dir(posixpath.join(root, "review"), uid=_REVIEW_UID)
    pick_by_copy(tb, root, review, ["job_005", "job_037"], src_name="output.log", rename="{cid}_output.log",
                 uid=_REVIEW_UID, mtime=at(730, 11))
    return tb.build()


# --------------------------------------------------------------------------
# 5. LC-MS instrument export: bulk, genuinely curated, still never MD.
# --------------------------------------------------------------------------

_MS_UID = 9501
_MS_REVIEWER_UID = 9550
_MS_ROOT = "/vol6/proteomics/export_2016"
_N_RUNS = 60


@register(
    kind="negative",
    description=(
        "LC-MS export: 60 templated run_#### dirs, each with acquisition.raw/acquisition.mzML from one uid "
        "on a regular 45-minute cadence, plus a human selected_runs/ copying three raw files out -- bulk and "
        "genuinely curated, but .raw/.mzML are never MD extensions so no campaign exists to pick from."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_ms_runs() -> Inventory:
    """60 numbered instrument runs plus a real human selection dir; still no MD class anywhere."""
    tb = TreeBuilder(root="/vol6", uid=_MS_UID)
    root = tb.dir(_MS_ROOT, uid=_MS_UID)
    for i in range(1, _N_RUNS + 1):
        run = tb.dir(posixpath.join(root, f"run_{i:04d}"), uid=_MS_UID)
        base = at(800, 6) + i * 2700
        tb.file(posixpath.join(run, "acquisition.raw"), size=2_000_000_000, mtime=base, uid=_MS_UID)
        tb.file(posixpath.join(run, "acquisition.mzML"), size=150_000_000, mtime=base + 600, uid=_MS_UID)
    selected = tb.dir(posixpath.join(root, "selected_runs"), uid=_MS_REVIEWER_UID)
    pick_by_copy(tb, root, selected, ["run_0007", "run_0031", "run_0045"], src_name="acquisition.raw",
                 rename="{cid}_acquisition.raw", uid=_MS_REVIEWER_UID, mtime=at(830, 9))
    return tb.build()
