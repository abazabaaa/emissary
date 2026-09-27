"""Negative group B4: automation masquerading as curation.

Thesis: machine-shaped work stays machine-shaped even when it has a
human-sounding name. Every scenario here embeds a real MD campaign (24
candidates, 10 trajectory chunks each, the shape the detector must recognize
in the grounded positive) and then adds a pipeline, cron job, report job,
bundling script or submission-script epilogue that *looks* like curation: an
approval-flavored directory name, derived-looking files, business-hours
timestamps, a different uid. None of them reflects a person looking at the
results and picking a subset, so an archivist would answer "nobody chose
these" in every case. Each scenario leans on a different defense or a
different blind spot of the detector (the 80% coverage cap on derived files,
the cap on copies of just the runs that finished, the
selection-confidence/coverage boundary, the "inside a candidate is not
evidence" rule, the shared-sha uniqueness gate, the derived rule's missing
uniqueness gate, and uid/time adjacency to the job), so no single broken
heuristic accounts for the whole group.

Adversarial review
------------------
Changed: (1) ``per_run_dropin`` and ``submission_postprocess`` descriptions
claimed per-run timing ("right after each run finishes", "3 minutes after
each one's last chunk") while the code keyed every file off the *campaign's*
last chunk; the descriptions now match the code, and the per-run timing got
its own scenario (``per_job_epilogue_daytime``). (2)
``cron_full_coverage_workhours_svc`` was 1a with better costume and the same
cue (derived at 100%); it is now ``cron_finished_only_workhours_svc``: 4 of 24
runs crashed and the service-account pipeline copies the restart file and
plots only the 20 that finished, which puts coverage at 83% (just above the
cap) and adds copy_out, a kind 1a does not use. (3) Added
``qc_symlink_farm_two_thirds``: the same finished-runs pipeline with 8 crashes,
16 of 24 = 67%, as a symlink farm. The detector picks all 16 (known gap). The
70% point (17 of 24) the brief suggested is caught, but only by the
selection-confidence gate: 1.0 x 7/24 = 0.292 < 0.3. At 16 the confidence is
0.333 and the detector breaks. (4) ``per_run_dropin`` now drops id-named
reports into 5 flagged runs (not all 24) under a service uid in working
hours, so the coverage cap cannot back up the inside-candidate rule. (5)
``boilerplate_hash_trap`` gained a per-candidate *unique* restart copy for
all 24 candidates in a sibling curated dir (unique sha, 100% coverage). It
sits in its own dir because files beside the boilerplate would put a
uniqueness failure into the same capped unit, and the cap would hide it. (6) Added
``reference_run_protocol_bundle``: a bundling script names boilerplate
copies after the reference run (``lig001_README.md``). The copy_out
uniqueness gate rejects them, but the derived rule has no such gate and
picks run_lig001 (known gap). (7) The two submitter-uid gaps now name the
signal that would separate them from a night-owl human on the same account.
Could not break: 100% derived coverage (1a) and 83% copy_out + derived
coverage (1b) under any uid and hour, because the cap only counts candidates.
Files inside candidates are never read at all. A sha shared by more than
one candidate never becomes copy_out. Tried splitting 1a's output into
per-candidate subdirectories (``analysis_final/lig001/lig001_rmsd.png`` +
``..._summary.csv``). Each subdir is curated on its own, but the
"everything below ``analysis_final``" unit covers 100% and the cap drops all
48 links. Tried 1a at 20 of 24 finished runs with derived only: caught at
83%. Below the cap, derived-only farms (weight 0.7) are saved by the
selection-confidence floor down to 14 of 24 picks (0.7 x 10/24 = 0.29). Copy, link and symlink
farms (weight 1.0) are saved only down to 17 (see 1c).
"""

from __future__ import annotations

import posixpath

from ..features import id_token
from ..inventory import Inventory
from ..synth import CampaignSpec, ExpectedOutcome, TreeBuilder, at, md_campaign, pick_by_derived, workday
from . import register

JOB_UID = 8001
"""uid of the submission script / job that runs every campaign in this module."""

SERVICE_UID = 8099
"""A pipeline service account: distinct from the submitter, and not a person."""

START = at(100, 3)
"""Shared campaign start: Wednesday 03:00, so the last chunk lands Friday 14:45 (working hours)."""

STAGGER_S = CampaignSpec().stagger_s
CHUNK_S = CampaignSpec().chunk_interval_s
N_CHUNKS = CampaignSpec().n_chunks

CAMPAIGN_SPAN_S = 23 * STAGGER_S + (N_CHUNKS - 1) * CHUNK_S
"""Seconds from the first candidate's first chunk to the last candidate's last chunk."""

ALL_24 = tuple(f"run_lig{i:03d}" for i in range(1, 25))
"""Candidate ids of the shared 24-run, 10-chunk amber campaign (``CampaignSpec`` defaults)."""

CRASHED_CHUNKS = 3
"""Chunks a crashed run managed to write before it died."""


def _campaign(tb: TreeBuilder, root: str, *, uid: int = JOB_UID, start: int = START,
              crashed: frozenset[int] = frozenset()) -> list[str]:
    """Lay down the shared 24-candidate campaign; the ``crashed`` indices stop after 3 chunks.

    Every run keeps its own slot in the job-array stagger (run ``i`` starts at
    ``start + (i-1)*STAGGER_S``), crashed or not, as on a real cluster.
    Returns the names of the runs that finished all 10 chunks.
    """
    done: list[str] = []
    for i in range(1, len(ALL_24) + 1):
        spec = CampaignSpec(uid=uid, start=start + (i - 1) * STAGGER_S, skip=frozenset(range(1, 25)) - {i},
                            n_chunks=CRASHED_CHUNKS if i in crashed else N_CHUNKS)
        names = md_campaign(tb, root, spec)
        if i not in crashed:
            done += names
    tb.file(posixpath.join(root, "submit_all.sh"), size=1_600, mtime=start - 600, uid=uid)
    return done


def _last_chunk(cid: str, start: int = START) -> int:
    """mtime of the last chunk of ``cid`` in an uncrashed 24-run campaign starting at ``start``."""
    c = int(cid.removeprefix("run_lig")) - 1
    return start + c * STAGGER_S + (N_CHUNKS - 1) * CHUNK_S


def _id(cid: str) -> str:
    return id_token(cid) or cid


# --------------------------------------------------------------------------
# 1a. Nightly cron job, full coverage, same uid, off-hours: caught by the
#     coverage cap even though the curated-dir score alone would pass.
# --------------------------------------------------------------------------

ROOT_1A = "/data/proj/PLPRO_A/md"
NIGHT_1A = at(106, 2)
"""Tuesday 02:00, four days after the campaign ends: off-hours."""


@register(
    kind="negative",
    description=(
        "Thesis: an approval-worded folder filled by cron is not curation; strongest cue: a nightly job "
        "writes an rmsd plot and a summary csv for all 24 candidates into 'analysis_final' under the "
        "submitter's uid at 02:00, and 100% coverage trips the cap even though name, derived mix and "
        "timing after the campaign score the dir as curated."
    ),
    expected=ExpectedOutcome.campaign_no_selection(ROOT_1A, cids=ALL_24),
)
def build_cron_full_coverage_offhours() -> Inventory:
    tb = TreeBuilder(root="/data")
    names = _campaign(tb, ROOT_1A)
    pipeline = posixpath.join(ROOT_1A, "analysis_final")
    pick_by_derived(tb, pipeline, names, suffix="_rmsd.png", uid=JOB_UID, mtime=NIGHT_1A)
    pick_by_derived(tb, pipeline, names, suffix="_summary.csv", uid=JOB_UID, mtime=NIGHT_1A + 1_800)
    return tb.build()


# --------------------------------------------------------------------------
# 1b. The pipeline only handles runs that FINISHED: 4 of 24 crashed, so it
#     covers 20/24 = 83%, just above the cap. It runs under a service
#     account in business hours and copies each run's unique restart file,
#     so copy_out (weight 1.0) and derived evidence are both capped.
# --------------------------------------------------------------------------

ROOT_1B = "/data/proj/PLPRO_B/md"
CRASHED_1B = frozenset({5, 11, 16, 22})
"""Runs that died after 3 chunks; the pipeline skips them."""
WORKDAY_1B = workday(100)
"""A weekday (day 140) well after the campaign ends, so 10:00 is working hours."""


@register(
    kind="negative",
    description=(
        "Thesis: 'every run that finished' is a machine's criterion, not a human's; strongest cue: a "
        "service-account pipeline copies prod.rst7 and writes a plot for exactly the 20 of 24 runs whose "
        "chunk series completed (4 crashed), so the curated 'final_structures' dir covers 83% of candidates "
        "and the cap drops both copy_out and derived even in business hours under a non-submitter uid."
    ),
    expected=ExpectedOutcome.campaign_no_selection(ROOT_1B, cids=ALL_24),
)
def build_cron_finished_only_workhours_svc() -> Inventory:
    tb = TreeBuilder(root="/data")
    done = _campaign(tb, ROOT_1B, crashed=CRASHED_1B)
    out = tb.dir(posixpath.join(ROOT_1B, "final_structures"), uid=SERVICE_UID)
    t = at(WORKDAY_1B, 10)
    for n, cid in enumerate(done):
        tb.copy(posixpath.join(ROOT_1B, cid, "prod.rst7"), posixpath.join(out, f"{_id(cid)}_final.rst7"),
                mtime=t + 3 * n, uid=SERVICE_UID)
        tb.file(posixpath.join(out, f"{_id(cid)}_rmsd.png"), size=60_000, mtime=t + 3 * n + 1, uid=SERVICE_UID)
    return tb.build()


# --------------------------------------------------------------------------
# 1c. The same finished-runs pipeline with 8 crashes: a nightly symlink farm
#     of the 16 completed runs, 67% coverage, below the cap and just above the
#     selection-confidence floor. KNOWN GAP.
# --------------------------------------------------------------------------

ROOT_1C = "/data/proj/PLPRO_F/md"
CRASHED_1C = frozenset({2, 5, 9, 11, 14, 17, 20, 23})
"""8 runs that died after 3 chunks (bad parameters for one ligand series)."""
NIGHT_1C = at(107, 2)
"""Wednesday 02:00 after the campaign: the nightly cron."""


@register(
    kind="negative",
    description=(
        "Thesis: a symlink farm of 'runs that completed' is an index, not a pick; strongest cue: a nightly "
        "cron under a service uid links exactly the 16 of 24 runs with complete chunk series into "
        "'analysis/converged', one link per second at 02:00, i.e. 100% of the completed runs."
    ),
    expected=ExpectedOutcome.campaign_no_selection(ROOT_1C, cids=ALL_24),
    known_gap=(
        "coverage_cap: the cap counts all 24 candidates, so a farm of the 16 completed runs (67%) is kept "
        "and selection confidence 1.0 x 8/24 = 0.33 clears the 0.3 floor (17 of 24 would give 0.29 and "
        "be caught). Signals that separate it from a human pick: (a) the linked set is exactly the set "
        "of candidates whose chunk series is complete (100% coverage of completed runs, where a human picks "
        "a small subset of them); (b) lockstep cadence: 16 links written 1 s apart at 02:00, where a "
        "human's links spread over minutes in working hours; (c) the candidate order of the links follows "
        "the run index."
    ),
)
def build_qc_symlink_farm_two_thirds() -> Inventory:
    tb = TreeBuilder(root="/data")
    done = _campaign(tb, ROOT_1C, crashed=CRASHED_1C)
    farm = tb.dir(posixpath.join(ROOT_1C, "analysis", "converged"), uid=SERVICE_UID)
    for n, cid in enumerate(done):
        tb.symlink(posixpath.join(farm, _id(cid)), f"../../{cid}/prod010.nc", mtime=NIGHT_1C + n, uid=SERVICE_UID)
    return tb.build()


# --------------------------------------------------------------------------
# 2. Post-campaign report job drops id-named reports INSIDE the 5 runs its
#    automatic RMSD check flagged. Only location protects the detector here:
#    5/24 is far below the cap.
# --------------------------------------------------------------------------

ROOT_2 = "/data/proj/PLPRO_C/md"
FLAGGED_2 = ("run_lig004", "run_lig009", "run_lig013", "run_lig019", "run_lig022")
"""Runs whose ligand drifted past the job's RMSD threshold."""
WORKDAY_2 = workday(98)
"""A weekday (day 136) after the campaign; the report job runs at 11:00."""


@register(
    kind="negative",
    description=(
        "Thesis: a report job that writes into run directories is annotating runs, not choosing them; "
        "strongest cue: '<id>_summary_final.pdf' and 'report.html' sit INSIDE 5 of 24 run dirs (flagged by "
        "an automatic RMSD threshold), and the detector never reads files inside candidates as evidence, "
        "even with a service uid, working hours and the candidate id in the name."
    ),
    expected=ExpectedOutcome.campaign_no_selection(ROOT_2, cids=ALL_24),
)
def build_per_run_dropin() -> Inventory:
    tb = TreeBuilder(root="/data")
    _campaign(tb, ROOT_2)
    t = at(WORKDAY_2, 11)
    for n, cid in enumerate(FLAGGED_2):
        run_dir = posixpath.join(ROOT_2, cid)
        tb.file(posixpath.join(run_dir, f"{_id(cid)}_summary_final.pdf"), size=180_000, mtime=t + 20 * n,
                uid=SERVICE_UID)
        tb.file(posixpath.join(run_dir, "report.html"), size=45_000, mtime=t + 20 * n + 5, uid=SERVICE_UID)
    return tb.build()


# --------------------------------------------------------------------------
# 3. Boilerplate hash trap: a convincing, working-hours, different-uid
#    "analysis" dir whose files are byte-identical to campaign boilerplate
#    shared by all 24 candidates (uniqueness gate), beside a sibling dir
#    where the same bundling run copied every candidate's unique restart
#    file (coverage cap). Each gate is tested in its own unit.
# --------------------------------------------------------------------------

ROOT_3 = "/data/proj/PLPRO_D/md"
ANALYST_UID_3 = 8501
WORKDAY_3 = workday(90)
"""A weekday (day 126) well after the campaign ends."""


@register(
    kind="negative",
    description=(
        "Thesis: copying what every run shares, or everything each run has, selects nothing; strongest "
        "cue: the 'analysis' dir's copies of README.txt and prod.in hash-match all 24 candidates (the "
        "uniqueness gate rejects them) and the sibling 'analysis/final_restarts' holds a unique restart for "
        "each of the 24 (the cap drops them), though both dirs score as curated."
    ),
    expected=ExpectedOutcome.campaign_no_selection(ROOT_3, cids=ALL_24),
)
def build_boilerplate_hash_trap() -> Inventory:
    tb = TreeBuilder(root="/data")
    names = _campaign(tb, ROOT_3)
    readme_id = f"{ROOT_3}:boilerplate:README.txt"
    for cid in names:
        tb.file(posixpath.join(ROOT_3, cid, "README.txt"), size=900, mtime=START - 500, uid=JOB_UID,
                content_id=readme_id)
    analysis = tb.dir(posixpath.join(ROOT_3, "analysis"), uid=ANALYST_UID_3)
    tb.file(posixpath.join(analysis, "meeting_notes.txt"), size=2_400, mtime=at(WORKDAY_3, 10), uid=ANALYST_UID_3)
    tb.copy(posixpath.join(ROOT_3, names[11], "README.txt"), posixpath.join(analysis, "README_copy.txt"),
            mtime=at(WORKDAY_3, 10, 5), uid=ANALYST_UID_3)
    tb.copy(posixpath.join(ROOT_3, names[11], "prod.in"), posixpath.join(analysis, "prod_in_copy.in"),
            mtime=at(WORKDAY_3, 10, 10), uid=ANALYST_UID_3)
    tb.file(posixpath.join(analysis, "protocol_final.in"), size=2_048, mtime=at(WORKDAY_3, 10, 15),
            uid=ANALYST_UID_3, content_id=f"{ROOT_3}:boilerplate:prod.in")
    restarts = tb.dir(posixpath.join(analysis, "final_restarts"), uid=ANALYST_UID_3)
    for n, cid in enumerate(names):
        tb.copy(posixpath.join(ROOT_3, cid, "prod.rst7"), posixpath.join(restarts, f"{_id(cid)}.rst7"),
                mtime=at(WORKDAY_3, 10, 20) + 2 * n, uid=ANALYST_UID_3)
    return tb.build()


# --------------------------------------------------------------------------
# 3b. Reference-run protocol bundle: a bundling script copies the shared
#     README.md/prod.in from the first run and prefixes them with its id.
#     KNOWN GAP (derived).
# --------------------------------------------------------------------------

ROOT_3B = "/data/proj/PLPRO_G/md"
ANALYST_UID_3B = 8502
WORKDAY_3B = workday(92)
"""A weekday (day 128) after the campaign; the bundle is made at 14:00."""


@register(
    kind="negative",
    description=(
        "Thesis: naming a boilerplate copy after the run it was taken from does not pick that run; "
        "strongest cue: 'lig001_README.md' and 'lig001_prod.in' in 'analysis/protocol_bundle' are "
        "byte-identical to files that all 24 candidates share, taken from run_lig001 only because it is "
        "the first run."
    ),
    expected=ExpectedOutcome.campaign_no_selection(ROOT_3B, cids=ALL_24),
    known_gap=(
        "derived: derived evidence checks only the id token in the name and mtime > t_end, not the file's "
        "sha, so 'lig001_README.md' (a .md copy of README.md, byte-identical in all 24 candidates) scores "
        "0.7 for run_lig001, while copy_out on the same file is correctly rejected by the uniqueness gate. "
        "Signal: a derived-extension file whose sha256 occurs in >= 2 candidates is boilerplate, not an "
        "artifact about one candidate; apply the uniqueness gate to derived too. Supporting signal: the "
        "named candidate is the lowest index (the script's reference run)."
    ),
)
def build_reference_run_protocol_bundle() -> Inventory:
    tb = TreeBuilder(root="/data")
    names = _campaign(tb, ROOT_3B)
    readme_id = f"{ROOT_3B}:boilerplate:README.md"
    for cid in names:
        tb.file(posixpath.join(ROOT_3B, cid, "README.md"), size=1_200, mtime=START - 500, uid=JOB_UID,
                content_id=readme_id)
    ref = names[0]
    bundle = tb.dir(posixpath.join(ROOT_3B, "analysis", "protocol_bundle"), uid=ANALYST_UID_3B)
    t = at(WORKDAY_3B, 14)
    for n, fname in enumerate(("README.md", "prod.in")):
        tb.copy(posixpath.join(ROOT_3B, ref, fname), posixpath.join(bundle, f"{_id(ref)}_{fname}"),
                mtime=t + n, uid=ANALYST_UID_3B)
    return tb.build()


# --------------------------------------------------------------------------
# 4a. Submission-script post-processing for 5 candidates, 3 minutes after
#     the WHOLE campaign's last chunk, off-hours, under the submitter's uid.
#     KNOWN GAP (curated_dir).
# --------------------------------------------------------------------------

ROOT_4 = "/data/proj/PLPRO_E/md"
START_4 = at(100, 20)
"""Wednesday 20:00 start, so the campaign ends Saturday 07:45 -- off-hours."""
END_4 = START_4 + CAMPAIGN_SPAN_S
CHOSEN_4 = ("run_lig003", "run_lig008", "run_lig012", "run_lig018", "run_lig021")
"""5 of the 24 candidates whose automatic convergence check passed -- not a human's subset."""


@register(
    kind="negative",
    description=(
        "Thesis: a batch epilogue's convergence filter is the script's selection, not a person's; "
        "strongest cue: 15 files ('<id>_dG_summary.csv', '<id>_top10.txt', '<id>_best_pose.pdb' for 5 of "
        "24 candidates) appear within 22 s, starting 180 s after the campaign's last chunk, at 07:48 on a "
        "Saturday, under the submitter's own uid."
    ),
    expected=ExpectedOutcome.campaign_no_selection(ROOT_4, cids=CHOSEN_4),
    known_gap=(
        "curated_dir: 'analysis' scores exactly 3 of 6 (approval word, 67% derived, written after the "
        "campaign) with owner == submitter and off-hours counting only as missed points, so 5 x 1.4 derived "
        "picks follow. A night-owl human on the same account would still differ in: (a) write density: 15 "
        "entries in 22 s (a scripted loop), where a person's writes are tens of seconds to minutes apart; "
        "(b) onset lock: the first write is 180 s after t_end, the job's own end, where a person arrives "
        "hours or days later; (c) a constant per-candidate template: exactly the same 3 suffixes per "
        "candidate (child-name diversity 0.2). Rule for hardening: owner == submitter and "
        "mtime_min - t_end < 1 h and burst rate > 1 file/10 s means pipeline, veto."
    ),
)
def build_submission_postprocess() -> Inventory:
    tb = TreeBuilder(root="/data")
    _campaign(tb, ROOT_4, start=START_4)
    analysis = tb.dir(posixpath.join(ROOT_4, "analysis"), uid=JOB_UID)
    base = END_4 + 180
    for n, cid in enumerate(CHOSEN_4):
        idn = _id(cid)
        t = base + 5 * n
        tb.file(posixpath.join(analysis, f"{idn}_dG_summary.csv"), size=3_200, mtime=t, uid=JOB_UID)
        tb.file(posixpath.join(analysis, f"{idn}_top10.txt"), size=1_100, mtime=t + 1, uid=JOB_UID)
        tb.file(posixpath.join(analysis, f"{idn}_best_pose.pdb"), size=42_000, mtime=t + 2, uid=JOB_UID)
    return tb.build()


# --------------------------------------------------------------------------
# 4b. Per-job epilogue: each converged run's own Slurm job writes its
#     summary 180 s after ITS last chunk, during Friday working hours. Only
#     the converged run that happens to finish last postdates t_end.
#     KNOWN GAP (curated_dir + derived).
# --------------------------------------------------------------------------

ROOT_4B = "/data/proj/PLPRO_H/md"
CONVERGED_4B = ("run_lig003", "run_lig008", "run_lig012", "run_lig018", "run_lig024")
"""Runs whose epilogue convergence check passed; lig024 happens to be the last run to finish."""
EPILOGUE_S = 180
"""Delay between a run's last chunk and its epilogue's output."""


@register(
    kind="negative",
    description=(
        "Thesis: output written by each run's own job epilogue is per-run bookkeeping, not a pick; "
        "strongest cue: every '<id>_*' file in 'analysis' lands exactly 180 s after its own candidate's "
        "last chunk, under the submitter's uid, interleaved with the still-running campaign."
    ),
    expected=ExpectedOutcome.campaign_no_selection(ROOT_4B, cids=CONVERGED_4B),
    known_gap=(
        "curated_dir: 'analysis' scores 3 of 6 (approval word, 67% derived, 100% working hours, because the "
        "runs end on a Friday between 09:30 and 14:45) though owner == submitter and 12 of its 15 files "
        "predate the campaign's end; derived ignores 4 of the 5 epilogues (mtime <= t_end) but accepts "
        "run_lig024's, whose run finished last, so exactly that one is picked. Signal: per-candidate "
        "offset lock: for every id-named file, mtime minus the named candidate's own last-chunk mtime is "
        "the same 180 s (+0..2 s), which a human's session never shows; the files also interleave with "
        "chunk writes. Rule for hardening: when owner == submitter and those offsets are constant "
        "across >= 3 candidates, the dir is the job's own output, veto."
    ),
)
def build_per_job_epilogue_daytime() -> Inventory:
    tb = TreeBuilder(root="/data")
    _campaign(tb, ROOT_4B)
    analysis = tb.dir(posixpath.join(ROOT_4B, "analysis"), uid=JOB_UID)
    for cid in CONVERGED_4B:
        idn, t = _id(cid), _last_chunk(cid) + EPILOGUE_S
        tb.file(posixpath.join(analysis, f"{idn}_dG_summary.csv"), size=3_200, mtime=t, uid=JOB_UID)
        tb.file(posixpath.join(analysis, f"{idn}_top10.txt"), size=1_100, mtime=t + 1, uid=JOB_UID)
        tb.file(posixpath.join(analysis, f"{idn}_best_pose.pdb"), size=42_000, mtime=t + 2, uid=JOB_UID)
    return tb.build()
