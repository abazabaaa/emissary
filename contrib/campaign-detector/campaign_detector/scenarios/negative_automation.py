"""Negative group B4: automation masquerading as curation.

Thesis: a human-sounding name on machine-shaped work is not evidence that a
human chose anything. Every scenario here embeds a real MD campaign (24
candidates, 10 trajectory chunks each -- the same shape the detector must
recognize in the grounded positive) and then adds a pipeline, cron job or
submission-script post-processing step that *looks* like curation -- an
approval-flavored directory name, derived-looking files, business-hours
timestamps, a different uid -- while never actually reflecting a human
picking a subset. Each scenario leans on a different one of the detector's
defenses (the 80% coverage cap, the "inside a candidate is not evidence"
rule, the shared-sha uniqueness gate, or uid/time adjacency) so that a
reviewer cannot dismiss the whole group by breaking one heuristic.
"""

from __future__ import annotations

import posixpath

from ..features import id_token
from ..inventory import Inventory
from ..synth import CampaignSpec, ExpectedOutcome, TreeBuilder, at, md_campaign, pick_by_derived, workday
from . import register

JOB_UID = 8001
"""uid of the submission script / job that runs every campaign in this module."""

START = at(100, 3)
"""Shared campaign start for scenarios 1-3 (03:00, so campaign end lands mid-afternoon)."""

CAMPAIGN_SPAN_S = 23 * 900 + 9 * 21600
"""Seconds from the first candidate's first chunk to the last candidate's last chunk
(23 staggers of 900s + 9 inter-chunk gaps of 21600s, the ``CampaignSpec`` defaults)."""

ALL_24 = tuple(f"run_lig{i:03d}" for i in range(1, 25))
"""Candidate ids of the shared 24-run, 10-chunk amber campaign (``CampaignSpec`` defaults)."""


def _campaign(tb: TreeBuilder, root: str, *, uid: int = JOB_UID, start: int = START) -> list[str]:
    """Lay down the shared 24-candidate, 10-chunk amber campaign under ``root``."""
    names = md_campaign(tb, root, CampaignSpec(uid=uid, start=start))
    tb.file(posixpath.join(root, "submit_all.sh"), size=1_600, mtime=start - 600, uid=uid)
    return names


# --------------------------------------------------------------------------
# 1a. Nightly cron job, full coverage, same uid, off-hours: caught by the
#     coverage cap even though the curated-dir score alone would pass.
# --------------------------------------------------------------------------

ROOT_1A = "/data/proj/PLPRO_A/md"
NIGHT_1A = at(106, 2)
"""02:00, several days after the campaign ends -- always off-hours regardless of weekday."""


@register(
    kind="negative",
    description=(
        "Thesis: a human-sounding directory name is not curation -- strongest cue: a nightly cron job writes "
        "an rmsd plot and a summary csv for EVERY one of the 24 candidates into 'analysis_final' under the "
        "submitter's own uid at lockstep 02:00 mtimes, so the 80% coverage cap strips all of it even though "
        "the name and the all-derived file mix alone would score as curated."
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
# 1b. Same pipeline, harder: a service account, working hours -- more
#     human-looking signals, still 100% coverage, still capped.
# --------------------------------------------------------------------------

ROOT_1B = "/data/proj/PLPRO_B/md"
SERVICE_UID_1B = 8099
"""A service account distinct from the submitter -- not a person's uid either."""

WORKDAY_1B = workday(100)
"""A weekday well after the campaign ends (day 140), so 10:00 there is real working hours."""


@register(
    kind="negative",
    description=(
        "Thesis: a human-sounding name is not curation even once it is dressed up further -- strongest cue: "
        "the same full-coverage plot+summary pipeline now runs under a distinct service account during "
        "business hours in 'curated_outputs', so uid and time-of-day both mimic a human yet 100% candidate "
        "coverage still triggers the cap, leaving the extra human-like signals unable to change the outcome."
    ),
    expected=ExpectedOutcome.campaign_no_selection(ROOT_1B, cids=ALL_24),
)
def build_cron_full_coverage_workhours_svc() -> Inventory:
    tb = TreeBuilder(root="/data")
    names = _campaign(tb, ROOT_1B)
    pipeline = posixpath.join(ROOT_1B, "curated_outputs")
    pick_by_derived(tb, pipeline, names, suffix="_rmsd.png", uid=SERVICE_UID_1B, mtime=at(WORKDAY_1B, 10))
    pick_by_derived(tb, pipeline, names, suffix="_summary.csv", uid=SERVICE_UID_1B, mtime=at(WORKDAY_1B, 10, 30))
    return tb.build()


# --------------------------------------------------------------------------
# 2. Per-run automatic report dropped INSIDE each candidate directory: it
#    can never even be read as evidence, since curated dirs must lie
#    outside every candidate.
# --------------------------------------------------------------------------

ROOT_2 = "/data/proj/PLPRO_C/md"
END_2 = START + CAMPAIGN_SPAN_S
"""mtime of the last trajectory chunk across the whole campaign."""


@register(
    kind="negative",
    description=(
        "Thesis: automation is not curation, and location forecloses the question here -- strongest cue: the "
        "pipeline drops 'summary_final.pdf' and 'report.html' INSIDE each of the 24 run directories right "
        "after each run finishes, so these human-sounding names sit inside a candidate and can never be read "
        "as curated-dir evidence, since the detector only scores directories outside every candidate."
    ),
    expected=ExpectedOutcome.campaign_no_selection(ROOT_2, cids=ALL_24),
)
def build_per_run_dropin() -> Inventory:
    tb = TreeBuilder(root="/data")
    names = _campaign(tb, ROOT_2)
    for n, cid in enumerate(names):
        run_dir = posixpath.join(ROOT_2, cid)
        mtime = END_2 + 60 * (n + 1)
        tb.file(posixpath.join(run_dir, "summary_final.pdf"), size=180_000, mtime=mtime, uid=JOB_UID)
        tb.file(posixpath.join(run_dir, "report.html"), size=45_000, mtime=mtime + 20, uid=JOB_UID)
    return tb.build()


# --------------------------------------------------------------------------
# 3. Boilerplate hash trap: a convincing, working-hours, different-uid
#    "analysis" dir whose every file is byte-identical to campaign
#    boilerplate shared by all 24 candidates -- the uniqueness gate (not
#    the coverage cap) rejects it before scoring.
# --------------------------------------------------------------------------

ROOT_3 = "/data/proj/PLPRO_D/md"
ANALYST_UID_3 = 8501
WORKDAY_3 = workday(90)
"""A weekday well after the campaign ends (day 126)."""


@register(
    kind="negative",
    description=(
        "Thesis: automation's fingerprint survives even inside a dir that looks fully human -- strongest cue: "
        "every artifact in a working-hours 'analysis' dir owned by a different uid (a copy of README.txt, a "
        "copy of prod.in, and a 'protocol_final.in') is byte-identical to boilerplate shared by all 24 "
        "candidates, so the shared-sha uniqueness gate rejects every one of them regardless of the convincing "
        "name, timing and ownership around them."
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
    tb.copy(posixpath.join(ROOT_3, names[0], "README.txt"), posixpath.join(analysis, "README_copy.txt"),
            mtime=at(WORKDAY_3, 10, 5), uid=ANALYST_UID_3)
    tb.copy(posixpath.join(ROOT_3, names[0], "prod.in"), posixpath.join(analysis, "prod_in_copy.in"),
            mtime=at(WORKDAY_3, 10, 10), uid=ANALYST_UID_3)
    tb.file(posixpath.join(analysis, "protocol_final.in"), size=2_048, mtime=at(WORKDAY_3, 10, 15),
            uid=ANALYST_UID_3, content_id=f"{ROOT_3}:boilerplate:prod.in")
    return tb.build()


# --------------------------------------------------------------------------
# 4. Submission-script post-processing for a handful of candidates, minutes
#    after each finishes, off-hours, under the submitter's own uid: human-
#    sounding filenames but the timing and ownership are the job's, not a
#    person's. Below the coverage cap (5 of 24), so if the curated-dir
#    heuristic is fooled by the name and derived-extension mix, the
#    detector will actually pick these -- a known gap, not a weakened test.
# --------------------------------------------------------------------------

ROOT_4 = "/data/proj/PLPRO_E/md"
START_4 = at(100, 20)
"""20:00 start, so the campaign ends ~07:45 two days later -- off-hours."""
END_4 = START_4 + CAMPAIGN_SPAN_S
CHOSEN_4 = ("run_lig003", "run_lig008", "run_lig012", "run_lig018", "run_lig021")
"""5 of the 24 candidates the same submission script post-processes -- not a human's subset."""


@register(
    kind="negative",
    description=(
        "Thesis: uid+time adjacency to the job, not a name, is what should disqualify this as curation -- "
        "strongest cue: the same submission script drops dG_summary.csv/top10.txt/best_pose.pdb for 5 of 24 "
        "candidates exactly 3 minutes after each one's last chunk, off-hours, under the submitter's own uid, "
        "which an archivist would call scripted post-processing rather than a human pick."
    ),
    expected=ExpectedOutcome.campaign_no_selection(ROOT_4, cids=CHOSEN_4),
    known_gap=(
        "curated_dir: an 'analysis' dir owned by the submitter, timestamped off-hours minutes after each "
        "run's last chunk, still scores 3 of 6 curated-dir criteria (approval word 'analysis', >=50% "
        "derived-extension files, entries newer than the campaign) because owner==submitter and off-hours "
        "timing are not counted against it; its per-candidate derived files for 5/24 candidates sit under "
        "the 80% coverage cap and are scored and picked, even though the uid and 3-minute timing offset are "
        "exactly the submission script's, not a human's."
    ),
)
def build_submission_postprocess() -> Inventory:
    tb = TreeBuilder(root="/data")
    _campaign(tb, ROOT_4, start=START_4)
    analysis = tb.dir(posixpath.join(ROOT_4, "analysis"), uid=JOB_UID)
    base = END_4 + 180
    for n, cid in enumerate(CHOSEN_4):
        idn = id_token(cid) or cid
        t = base + 5 * n
        tb.file(posixpath.join(analysis, f"{idn}_dG_summary.csv"), size=3_200, mtime=t, uid=JOB_UID)
        tb.file(posixpath.join(analysis, f"{idn}_top10.txt"), size=1_100, mtime=t + 1, uid=JOB_UID)
        tb.file(posixpath.join(analysis, f"{idn}_best_pose.pdb"), size=42_000, mtime=t + 2, uid=JOB_UID)
    return tb.build()
