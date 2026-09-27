"""Negative group B3: copies that aren't selections.

Thesis: a copy of candidate data is evidence of a human *pick* only when it
is a genuine, discriminating subset of the candidates, made by a person, and
still live. Every scenario lays down a real MD campaign (>= 24 candidates,
>= 10 trajectory chunks, submitted at 03:00 on a Monday like the grounded
positive) and then a copy fingerprint that could pass for a selection. The
detector must find the one real campaign and report zero picks for it.

Ground truth, argued per scenario (what an archivist would say)
---------------------------------------------------------------

* ``mirror_backup`` -- a ``cp -p`` of the whole project into ``backup/``
  contains every byte a second time. Nobody chose anything by copying all
  of it. The campaign is the original (earlier ctime). The copy of
  ``analysis/`` holds nothing the original doesn't.
* ``rsync_mirror`` -- the run dirs were rsync'd to a DR site right after the
  campaign. Later the working copy was lost and restored *from* that site,
  so the working copy now has the later ctimes. Content is identical and
  there are no picks either way. The campaign an archivist names is the
  working copy: it alone holds the submit script and the analysis dir.
  ctime points the other way, so the detector picks the wrong root.
* ``symlink_index`` -- two indexes link every run. An index of everything is
  navigation. Calling one ``all_runs_final`` does not make it a shortlist.
* ``hardlink_farm`` -- a per-ligand working set (``analysis/links/<cid>/``
  with the final chunk hard-linked in and an RMSD plot next to it) for every
  ligand. Analysing everything is not choosing, and the fact that it is
  looked at through ``ln`` rather than ``ln -s`` or ``cp`` changes nothing.
* ``tarball_archive`` -- a colleague tars every run for tape. Packing all of
  it away is housekeeping, and a tarball is opaque to both hash matching
  and derived-name matching.
* ``discard_copies`` -- ten renamed copy-outs, but every one sits under
  ``old``, ``BackUp``, ``trash``, ``scratch`` or ``figs_v3/tmp``. The
  analyst wrote them off: a stash, not a pick.
* ``backup_only_analysis`` -- a curated analysis shaped exactly like the
  grounded positive (three renamed copy-outs, summary sheet, slides). It
  survives only inside ``backup/``. The live project has no analysis dir. An
  archivist can say "someone once looked at these three", but the live tree
  shows no choice: the curation was deleted or never promoted. The
  conservative call is no picks. A richer label (historical selection) is a
  hardening idea, not something to fake here.
* ``coverage_cap_90`` -- 27 of 30 copied by hand over three afternoons, with
  renames. The information is in the three left out, not in the 27 kept:
  "which did the human pick?" has no discriminating answer. That is a
  mirror with three failures, however human the cadence.
* ``coverage_cap_70`` -- see below.

At what coverage does copying stop being a choice?
--------------------------------------------------

3 of 30 is a choice. 27 of 30 is a mirror with three failures. 21 of 30
(70%) is ambiguous, and coverage alone cannot settle it. A script keeping
"everything that finished" is not choosing. A person keeping the 21 they
liked is. The inventory tells them apart by *shape*:

* **Cadence.** A script copies in one burst, in candidate order, at a
  constant interval (or at a constant offset from each run's end, as an
  epilogue would). A person copies over several sessions and days, out of
  candidate order, interleaved with notes and plots.
* **Names.** A mirror keeps names: ``selected70/run_cpd001/prod010.dcd``
  mirrors ``dock/run_cpd001/prod010.dcd``. A person renames
  (``cpd007_nice_pose.dcd``). Renames are the strongest single cue.
* **Predicate.** If the covered set equals a set the machine can compute,
  it was computed. Example: exactly the runs whose chunk series reached the
  last chunk.

``coverage_cap_70`` encodes the machine-shaped 70%: 9 runs crashed at chunk
6, and one analyst burst (constant 2-minute cadence, candidate order)
mirrors ``prod010.dcd`` + ``prod.coor`` of exactly the 21 finished runs with
names and layout preserved. It is an honest negative and a KNOWN GAP. The
coverage cap is 0.8, and
``selection_confidence = 1.0 * (1 - 21/30) = 0.30`` sits exactly on
``Params.selection_conf``. The revert test is ``<``, not ``<=``, so all 21
are picked.

The **human-shaped 70% twin**, an honest *positive* for the hardening unit to
encode in a positive module (not here), has the same campaign with the same
9 crashed runs. The analyst copies 21 of the runs, *including* some crashed
ones and *excluding* some finished ones, so the set is no machine predicate.
The copies land over four afternoons on different workdays, out of
candidate order, each hand-renamed (``cpd007_nice_pose.dcd``,
``cpd012_keep_v2.dcd``, ``cpd019_for_MedChem.dcd``), in a flat
``shortlist/`` with ``notes.txt`` and a ``ranking.xlsx`` edited in between
bursts. Expected: those 21 picked, the other 9 not_picked. Today the detector
gets both 70% scenarios "right" only through the ``<`` boundary. Flipping it
to ``<=`` fixes the negative and breaks the positive. That is why the rule
below uses shape, not a nudged threshold.

Recommended rule for the hardening unit
---------------------------------------

Keep the 0.8 hard cap. Between 0.5 and 0.8 of the candidates (the ambiguous
band), drop a covering unit (label its candidates unknown, with a note) when
it is machine-shaped: (a) >= 0.9 of its copies keep the source basename, or
mirror the source path relative to the campaign root; (b) its copies form
one burst (``count_bursts == 1``) whose inter-copy intervals are regular
(``chunk_regularity`` >= 0.9) in candidate-id order; or (c) its candidate
set equals a campaign-computable predicate (complete chunk series,
successful scheduler log). Keep it as picks when it spans >= 2 bursts on
different days and at least half the copies are renamed. The
``selection_conf`` comparison can stay ``<``. It is a backstop, not the
decision.

Adversarial review
------------------

What changed, relative to the writer's draft:

* ``_cp_p_mirror`` now carries the *source's* content id. Before, it used
  the source path, which broke boilerplate (``prod.in``) and any copy
  inside the source tree: a byte-identical mirror had different hashes. The
  new helper recovers the content id from the snapshot's sha256 alone.
* ``mirror_backup`` now mirrors a project whose analysis dir also holds the
  positive's stray ``analysis/old/`` copy-out.
* ``rsync_mirror`` was inverted: the DR mirror has the EARLIER ctimes and the
  restored working copy (submit script + analysis) the later ones. KNOWN
  GAP: the detector reports the DR mirror as the campaign.
* ``symlink_index``: the ``all_runs_final`` index was split into
  per-candidate subdirectories of two links each. No direct unit covers
  now; only the minimal-subtree rule of the cap catches it.
* New ``hardlink_farm``: the cap must also drop hard-link evidence. Each
  per-ligand dir is curated, so the evidence is really collected, then
  capped. A flat ``links/`` of bare hard links never reaches curated
  status: inode-shared metadata gives it the submitter's uid and run-time
  mtimes. It would pass for the wrong reason, so it is not used.
* ``tarball_archive`` was made curated. It is human-run (analyst uid,
  working hours, after the campaign, with a MANIFEST.md), so the
  opaque-format cue is what really holds, not the curated gate.
* ``discard_copies`` now exercises the joined-token taint (``BackUp``) and a
  discard dir nested under a versioned, non-tainted dir (``figs_v3/tmp``).
* New ``backup_only_analysis``, the closest-to-positive negative here: the
  grounded positive's curation, moved under ``backup/``.
* ``coverage_cap_90`` is now human-shaped (three afternoons, three rename
  styles, a notes file). ``coverage_cap_70`` is machine-shaped (one burst,
  names preserved, exactly the finished runs). Their known-gap text names
  the ``<`` boundary and the cadence/rename signal.

What I tried and could not break:

* Uniqueness under a mirror. I gave the original ``analysis/`` of
  ``mirror_backup`` three picks: a renamed copy of lig012, a
  ``lig019_rmsd.png``, and a relative symlink to lig021. The detector still
  credits all three to the original, with the other 21 not_picked. The
  copy-out's hash now sits under the original candidate *and* its mirror,
  but ``_unique_owner`` only counts the candidates of the campaign being
  evaluated, and the mirror's candidates belong to a ctime-gated copy root.
  The result is the same with the mirror at an untainted ``snapshots/``
  path. There the mirrored analysis becomes a second curated dir: its
  copy-out and plot credit the *same* candidates, and its relative symlink
  resolves inside the mirror, so it credits nothing. The hardening unit
  should encode this positive twin, expecting picks {run_lig012,
  run_lig019, run_lig021} with the rest not_picked.
* Partial mirrors: the overlap of a subset with its source is always 1.0.
* Taint on a curated dir's ancestor: taint is anchored at the common
  ancestor with the campaign root, so ``/vol3/backup/...`` is tainted even
  though the live root is not under it.

Cue ablation (scratch probe, not a test): I switched off each scenario's
claimed cue and confirmed the detector is then fooled.

* ``mirror_backup``: ``copy_overlap`` off gives two campaign roots. With
  NEG_WORDS off it still passes, because the mirrored analysis has nothing
  to credit, so the ctime gate alone is load-bearing.
* ``symlink_index`` and ``hardlink_farm``: cap and selection gate off give
  24 picks each.
* ``discard_copies``: NEG_WORDS off gives 10 picks.
* ``backup_only_analysis``: NEG_WORDS off gives the 3 picks.
* ``coverage_cap_90``: cap off still gives 0 picks, because selection
  confidence 0.10 is below 0.30. Both off gives 27. There are two
  independent layers.
* ``tarball_archive``: cap and selection gate off still give 0 picks. The
  opaque format is the cue; no evidence ever exists.
* ``coverage_cap_70`` (the machine-shaped 70% case): the ``selected70/<cid>``
  directories are also newer than the campaign and carry candidate ids, so
  they add 21 ``graduation`` hits (0.5 each), also at 70%.
* The human-shaped 70% twin: built in the probe, it gets 21 picks at
  selection confidence 0.30. With a ``<=`` boundary it gets 0. That is the
  evidence that the boundary must not be the fix.
"""

from __future__ import annotations

import hashlib
import posixpath

from ..inventory import Entry, Inventory
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy,
    pick_by_symlink, workday,
)
from . import register


def _names(spec: CampaignSpec) -> list[str]:
    """The candidate directory names ``md_campaign`` will produce for ``spec``."""
    return [spec.candidate_fmt.format(i) for i in range(1, spec.n_candidates + 1) if i not in spec.skip]


def _wd(day: int, k: int) -> int:
    """Day number of the ``k``-th workday after the Monday ``day`` (``day`` must be a multiple of 7)."""
    assert day % 7 == 0, "campaign starts are Mondays"
    return workday(5 * (day // 7) + k)


def _sha(content_id: str) -> str:
    return hashlib.sha256(b"cd:" + content_id.encode()).hexdigest()


def _content_id(snap: Inventory, e: Entry) -> str:
    """The synthetic content id behind ``e.sha256``.

    Tries the file's own path, then the paths of files with the same hash
    (``e`` is itself a copy), then the per-campaign boilerplate id of every
    ancestor (``md_campaign`` shares one id per boilerplate name).
    """
    if _sha(e.path) == e.sha256:
        return e.path
    for other in snap.by_sha.get(e.sha256 or "", ()):
        if _sha(other.path) == e.sha256:
            return other.path
    anc = e.parent
    while anc:
        cid = f"{anc}:boilerplate:{e.name}"
        if _sha(cid) == e.sha256:
            return cid
        anc = posixpath.dirname(anc) if anc != "/" else None
    raise ValueError(f"cannot recover content id of {e.path}")


def _cp_p_mirror(tb: TreeBuilder, snap: Inventory, src_root: str, dst_root: str, *, ctime: int) -> None:
    """Recursively ``cp -p`` / ``rsync -a`` ``src_root`` of ``snap`` to ``dst_root``.

    Names, tree shape, mtimes, ownership and bytes (sha256, including shared
    boilerplate) are preserved; files get the new ``ctime`` (the detector's
    mirror gate reads trajectory-file ctimes). Symlink targets are copied
    verbatim, so relative links resolve inside the copy.
    """
    src_root = src_root.rstrip("/") or "/"
    for e in snap.subtree(src_root):
        dst = dst_root + e.path[len(src_root):]
        if e.kind == "d":
            tb.dir(dst, uid=e.uid)
        elif e.kind == "f":
            tb.file(dst, size=e.size, mtime=e.mtime, uid=e.uid, content_id=_content_id(snap, e), ctime=ctime)
        else:
            tb.symlink(dst, e.target or "", mtime=e.mtime, uid=e.uid)


# --------------------------------------------------------------------------
# 1. Byte-identical backup mirror of the whole project (incl. analysis/)
# --------------------------------------------------------------------------

S1_PROJECT = "/vol7/projects/ABT_2012"
S1_ROOT = S1_PROJECT + "/md"
S1_BACKUP = "/vol7/backup/2012-03/ABT_2012"
S1_DAY = -3227
S1_SPEC = CampaignSpec(engine="amber", n_candidates=24, candidate_fmt="run_lig{:03d}", n_chunks=10, uid=2101,
                       start=at(S1_DAY, 3))
S1_ANALYST = 3101


def _s1_project(tb: TreeBuilder) -> str:
    """The live ABT project: campaign, submit script, analysis dir with a stray copy in ``old/``."""
    md_campaign(tb, S1_ROOT, S1_SPEC)
    tb.file(posixpath.join(S1_ROOT, "submit_all.sh"), size=1_600, mtime=S1_SPEC.start - 600, uid=S1_SPEC.uid)
    analysis = human_analysis(tb, S1_PROJECT, AnalysisSpec(uid=S1_ANALYST, first_workday=5 * (S1_DAY // 7) + 15))
    old = tb.dir(posixpath.join(analysis, "old"), uid=S1_ANALYST)
    tb.copy(posixpath.join(S1_ROOT, "run_lig005", "prod010.nc"), posixpath.join(old, "lig005_prod010.nc"),
            uid=S1_ANALYST, mtime=at(_wd(S1_DAY, 16), 9, 30))
    return analysis


@register(
    kind="negative",
    description="a byte-identical cp -p backup of the whole project (runs, analysis/, analysis/old/) is not a "
                "second campaign and not a selection; strongest cue: the ctime ordering of two hash-identical "
                "roots, which marks the later one as the copy",
    expected=ExpectedOutcome.campaign_no_selection(S1_ROOT, cids=_names(S1_SPEC)),
    name="mirror_backup",
)
def build_mirror_backup() -> Inventory:
    """A modeller's project (campaign + analysis notes, no picks) is backed up byte-for-byte in March 2012."""
    tb = TreeBuilder(root="/vol7")
    _s1_project(tb)
    _cp_p_mirror(tb, tb.build(), S1_PROJECT, S1_BACKUP, ctime=at(-3101, 9))
    return tb.build()


# --------------------------------------------------------------------------
# 2. rsync DR mirror, then the working copy is restored from it (ctime inverted)
# --------------------------------------------------------------------------

S2_PROJECT = "/vol9/site1/PROJ_2013"
S2_ROOT = S2_PROJECT + "/dock"
S2_MIRROR = "/vol9/site2/PROJ_2013/dock"
S2_DAY = -2653
S2_SPEC = CampaignSpec(engine="gromacs", n_candidates=24, candidate_fmt="run_mol{:03d}", n_chunks=10, uid=2205,
                       start=at(S2_DAY, 3))
S2_ANALYST = 3205


@register(
    kind="negative",
    description="run dirs are rsync'd to a DR site the week after the campaign, then the working copy is "
                "restored from that site, so the true campaign (the one with submit_all.sh and analysis/) has "
                "the LATER ctimes; strongest cue: provenance (submit script and human analysis live only "
                "beside the working copy), which contradicts the ctime order",
    expected=ExpectedOutcome.campaign_no_selection(S2_ROOT, cids=_names(S2_SPEC)),
    known_gap="campaign_root: mirror gate decides by ctime only; the restored working copy (submit_all.sh, "
              "analysis/) has later ctimes than its DR mirror, so the mirror is reported as the campaign",
    name="rsync_mirror",
)
def build_rsync_mirror() -> Inventory:
    """A GROMACS docking campaign: DR rsync to site2, disk loss at site1, restore from site2, then analysis."""
    scratch = TreeBuilder(root="/vol9")
    names = md_campaign(scratch, S2_ROOT, S2_SPEC)
    scratch.file(posixpath.join(S2_ROOT, "submit_all.sh"), size=1_400, mtime=S2_SPEC.start - 600,
                 uid=S2_SPEC.uid)
    snap = scratch.build()
    tb = TreeBuilder(root="/vol9")
    for cid in names:  # rsync -a of the run dirs only, one week after the campaign
        _cp_p_mirror(tb, snap, posixpath.join(S2_ROOT, cid), posixpath.join(S2_MIRROR, cid),
                     ctime=at(S2_DAY + 7, 22))
    _cp_p_mirror(tb, snap, S2_ROOT, S2_ROOT, ctime=at(S2_DAY + 35, 14))  # restore, five weeks after
    human_analysis(tb, S2_ROOT, AnalysisSpec(uid=S2_ANALYST, first_workday=5 * (S2_DAY // 7) + 27))
    return tb.build()


# --------------------------------------------------------------------------
# 3. Symlink index with 100% coverage, flat and nested
# --------------------------------------------------------------------------

S3_PARENT = "/vol4/archive/PRJ_2014"
S3_ROOT = S3_PARENT + "/screen"
S3_ALL_RUNS = S3_PARENT + "/all_runs"
S3_ALL_RUNS_FINAL = S3_PARENT + "/all_runs_final"
S3_DAY = -2408
S3_SPEC = CampaignSpec(engine="desmond", n_candidates=24, candidate_fmt="run_frag{:03d}", n_chunks=10, uid=2310,
                       start=at(S3_DAY, 3))
S3_INDEXER = 3310


@register(
    kind="negative",
    description="two convenience symlink indexes link every run, one flat (all_runs/) and one split into "
                "per-candidate subdirs under an approval-sounding name (all_runs_final/<cid>/); strongest cue: "
                "100% symlink coverage, caught per directory for the flat index and only by the minimal "
                "covering subtree for the nested one",
    expected=ExpectedOutcome.campaign_no_selection(S3_ROOT, cids=_names(S3_SPEC)),
    name="symlink_index",
)
def build_symlink_index() -> Inventory:
    """A fragment-screening campaign gets two symlink farms indexing every single run."""
    tb = TreeBuilder(root="/vol4")
    names = md_campaign(tb, S3_ROOT, S3_SPEC)
    pick_by_symlink(tb, dst_dir=S3_ALL_RUNS, campaign_root=S3_ROOT, cids=names, uid=S3_INDEXER,
                    mtime=at(S3_DAY + 91, 10), src_name="traj010.dcd", link_name="{cid}")
    for n, cid in enumerate(names):
        sub = posixpath.join(S3_ALL_RUNS_FINAL, cid)
        t = at(S3_DAY + 93, 11) + 120 * n
        pick_by_symlink(tb, dst_dir=sub, campaign_root=S3_ROOT, cids=[cid], uid=S3_INDEXER, mtime=t,
                        src_name="traj010.dcd", link_name="traj.dcd")
        pick_by_symlink(tb, dst_dir=sub, campaign_root=S3_ROOT, cids=[cid], uid=S3_INDEXER, mtime=t + 30,
                        src_name="checkpoint.chk", link_name="checkpoint.chk")
    return tb.build()


# --------------------------------------------------------------------------
# 4. Hard-link farm: per-ligand working set for every ligand
# --------------------------------------------------------------------------

S4H_ROOT = "/vol8/projects/EGFR_2015/md"
S4H_LINKS = S4H_ROOT + "/analysis/links"
S4H_DAY = -1953
S4H_SPEC = CampaignSpec(engine="amber", n_candidates=24, candidate_fmt="run_lig{:03d}", n_chunks=10, uid=2810,
                        start=at(S4H_DAY, 3))
S4H_ANALYST = 3810


@register(
    kind="negative",
    description="an analysis script hard-links the last chunk of every run into analysis/links/<cid>/ next to a "
                "per-ligand rmsd.png, so each per-ligand dir is curated and yields a genuine hardlink; strongest "
                "cue: 100% hardlink coverage, which the coverage cap must drop just like symlinks and copies",
    expected=ExpectedOutcome.campaign_no_selection(S4H_ROOT, cids=_names(S4H_SPEC)),
    name="hardlink_farm",
)
def build_hardlink_farm() -> Inventory:
    """An EGFR campaign whose analyst builds an ``ln``-based working set of every ligand."""
    tb = TreeBuilder(root="/vol8")
    names = md_campaign(tb, S4H_ROOT, S4H_SPEC)
    human_analysis(tb, S4H_ROOT, AnalysisSpec(uid=S4H_ANALYST, first_workday=5 * (S4H_DAY // 7) + 12))
    t = at(_wd(S4H_DAY, 10), 13)
    for n, cid in enumerate(names):
        sub = tb.dir(posixpath.join(S4H_LINKS, cid), uid=S4H_ANALYST)
        tb.hardlink(posixpath.join(S4H_ROOT, cid, "prod010.nc"), posixpath.join(sub, "prod010.nc"))
        tb.file(posixpath.join(sub, "rmsd.png"), size=55_000, mtime=t + 90 * n, uid=S4H_ANALYST)
    return tb.build()


# --------------------------------------------------------------------------
# 5. Per-run tarball archive made by a human: opaque to hash and name matching
# --------------------------------------------------------------------------

S5T_PARENT = "/vol2/proj/RSV_2015"
S5T_ROOT = S5T_PARENT + "/simulate"
S5T_ARCHIVE = S5T_PARENT + "/archive"
S5T_DAY = -2072
S5T_SPEC = CampaignSpec(engine="namd", n_candidates=24, candidate_fmt="run_pose{:03d}", n_chunks=10, uid=2410,
                        start=at(S5T_DAY, 3))
S5T_ARCHIVIST = 3410


@register(
    kind="negative",
    description="a colleague tars every run into archive/<cid>.tar.gz plus a MANIFEST.md in one working-hours "
                "afternoon, so archive/ is a curated dir with a candidate-named entry per run; strongest cue: a "
                "tarball matches neither a candidate file hash nor a DERIVED_EXTS name, so it is never evidence",
    expected=ExpectedOutcome.campaign_no_selection(S5T_ROOT, cids=_names(S5T_SPEC)),
    name="tarball_archive",
)
def build_tarball_archive() -> Inventory:
    """An RSV NAMD campaign is packed for tape by a colleague, one tarball per run."""
    tb = TreeBuilder(root="/vol2")
    names = md_campaign(tb, S5T_ROOT, S5T_SPEC)
    t = at(_wd(S5T_DAY, 60), 13)
    tb.file(posixpath.join(S5T_ARCHIVE, "MANIFEST.md"), size=6_000, mtime=t - 600, uid=S5T_ARCHIVIST)
    for n, cid in enumerate(names):
        tb.file(posixpath.join(S5T_ARCHIVE, f"{cid}.tar.gz"), size=S5T_SPEC.n_chunks * S5T_SPEC.chunk_size // 2,
                mtime=t + 480 * n, uid=S5T_ARCHIVIST)
    return tb.build()


# --------------------------------------------------------------------------
# 6. Copy-outs that exist only inside discard directories
# --------------------------------------------------------------------------

S6D_ROOT = "/vol5/screens/JAK2_2016/fep"
S6D_DAY = -1645
S6D_SPEC = CampaignSpec(engine="amber", n_candidates=24, candidate_fmt="run_lig{:03d}", n_chunks=10, uid=2510,
                        start=at(S6D_DAY, 3))
S6D_ANALYST = 3510


@register(
    kind="negative",
    description="an analyst makes ten renamed working-hours copy-outs of ten candidates, two in each of "
                "analysis/old, BackUp, trash, scratch and analysis/figs_v3/tmp (each would be curated without "
                "its taint); strongest cue: the NEG_WORDS taint, including the joined token in 'BackUp' and a "
                "discard dir nested below a versioned dir",
    expected=ExpectedOutcome.campaign_no_selection(S6D_ROOT, cids=_names(S6D_SPEC)),
    name="discard_copies",
)
def build_discard_copies() -> Inventory:
    """A JAK2 FEP campaign is analysed, but every copy-out the analyst makes lands in a discard directory."""
    tb = TreeBuilder(root="/vol5")
    names = md_campaign(tb, S6D_ROOT, S6D_SPEC)
    analysis = human_analysis(tb, S6D_ROOT, AnalysisSpec(uid=S6D_ANALYST, first_workday=5 * (S6D_DAY // 7) + 10))
    day = _wd(S6D_DAY, 13)
    for dst, cids, rename, hour in (
        (posixpath.join(analysis, "old"), names[0:2], "{id}_bestpose.nc", 11),
        (posixpath.join(S6D_ROOT, "BackUp"), names[2:4], "{id}_keep.nc", 12),
        (posixpath.join(S6D_ROOT, "trash"), names[4:6], "{id}_v2.nc", 13),
        (posixpath.join(S6D_ROOT, "scratch"), names[6:8], "{id}_check.nc", 14),
        (posixpath.join(analysis, "figs_v3", "tmp"), names[8:10], "{id}_fig.nc", 15),
    ):
        pick_by_copy(tb, campaign_root=S6D_ROOT, dst_dir=dst, cids=cids, uid=S6D_ANALYST, mtime=at(day, hour),
                     rename=rename)
    return tb.build()


# --------------------------------------------------------------------------
# 7. A positive-shaped curation that survives only in a backup mirror
# --------------------------------------------------------------------------

S7_PROJECT = "/vol3/projects/HIV_2014"
S7_ROOT = S7_PROJECT + "/md"
S7_BACKUP = "/vol3/backup/2014-11/HIV_2014"
S7_DAY = -2254
S7_SPEC = CampaignSpec(engine="gromacs", n_candidates=24, candidate_fmt="run_cpd{:03d}", n_chunks=10, uid=2910,
                       start=at(S7_DAY, 3))
S7_ANALYST = 3910


@register(
    kind="negative",
    description="a curated analysis dir shaped like the grounded positive (three renamed copy-outs, sheet, "
                "slides, notes) exists only inside a backup/ mirror of the project; the live tree has no "
                "analysis dir; strongest cue: the backup ancestor taints the whole curated dir, so the live "
                "tree shows no choice",
    expected=ExpectedOutcome.campaign_no_selection(S7_ROOT, cids=_names(S7_SPEC)),
    name="backup_only_analysis",
)
def build_backup_only_analysis() -> Inventory:
    """HIV project: analysis with 3 picks is backed up, then deleted from the live project."""
    full = TreeBuilder(root="/vol3")
    md_campaign(full, S7_ROOT, S7_SPEC)
    analysis = human_analysis(full, S7_PROJECT, AnalysisSpec(
        uid=S7_ANALYST, first_workday=5 * (S7_DAY // 7) + 15,
        files=("hits_summary_v2.xlsx", "notes.txt", "HIV_topHits_forMedChem.pptx", "README.md"),
    ))
    for n, cid in enumerate(("run_cpd004", "run_cpd011", "run_cpd019")):
        pick_by_copy(full, S7_ROOT, analysis, [cid], src_name="traj010.xtc", rename="{id}_bestpose.xtc",
                     uid=S7_ANALYST, mtime=at(_wd(S7_DAY, 16 + 2 * n), 14, 30))
    tb = TreeBuilder(root="/vol3")
    md_campaign(tb, S7_ROOT, S7_SPEC)  # the live project: deterministic, identical campaign, analysis gone
    _cp_p_mirror(tb, full.build(), S7_PROJECT, S7_BACKUP, ctime=at(S7_DAY + 126, 9))
    return tb.build()


# --------------------------------------------------------------------------
# 8. Bulk copy-out above the coverage cap (human-shaped) and below it (machine-shaped, known gap)
# --------------------------------------------------------------------------

S8A_PARENT = "/vol6/hts/COVID_2017"
S8A_ROOT = S8A_PARENT + "/dock"
S8A_SELECTED = S8A_PARENT + "/selected"
S8A_DAY = -1225
S8A_SPEC = CampaignSpec(engine="gromacs", n_candidates=30, candidate_fmt="run_cpd{:03d}", n_chunks=10, uid=2610,
                        start=at(S8A_DAY, 3))
S8A_ANALYST = 3610


@register(
    kind="negative",
    description="a person copies 27 of 30 candidates into selected/ over three afternoons with three rename "
                "styles and a notes file, i.e. every human cue except discrimination; strongest cue: 90% "
                "coverage, above the 0.8 cap, where the information lies in the three left out",
    expected=ExpectedOutcome.campaign_no_selection(S8A_ROOT, cids=_names(S8A_SPEC)),
    name="coverage_cap_90",
)
def build_coverage_cap_90() -> Inventory:
    """A COVID docking screen where the analyst keeps all but three, by hand, over three afternoons."""
    tb = TreeBuilder(root="/vol6")
    names = md_campaign(tb, S8A_ROOT, S8A_SPEC)
    kept = [c for c in names if c not in ("run_cpd008", "run_cpd017", "run_cpd026")]
    tb.file(posixpath.join(S8A_SELECTED, "notes.txt"), size=3_000, mtime=at(_wd(S8A_DAY, 20), 13, 50),
            uid=S8A_ANALYST)
    for k, rename in enumerate(("{id}_ok.xtc", "{id}_keep.xtc", "{id}_v2.xtc")):
        pick_by_copy(tb, campaign_root=S8A_ROOT, dst_dir=S8A_SELECTED, cids=kept[k::3], uid=S8A_ANALYST,
                     mtime=at(_wd(S8A_DAY, 20 + 3 * k), 14), src_name="traj010.xtc", rename=rename)
    return tb.build()


S8B_PARENT = "/vol6/hts/COVID_2018b"
S8B_ROOT = S8B_PARENT + "/dock"
S8B_SELECTED = S8B_PARENT + "/selected70"
S8B_DAY = -889
S8B_CRASHED = frozenset({3, 7, 10, 13, 17, 20, 24, 27, 30})
"""The nine runs that died after chunk 6 (never wrote ``prod010.dcd``)."""
S8B_SPEC = CampaignSpec(engine="namd", n_candidates=30, candidate_fmt="run_cpd{:03d}", n_chunks=10, uid=2710,
                        start=at(S8B_DAY, 3), skip=S8B_CRASHED)
S8B_CRASHED_SPEC = CampaignSpec(engine="namd", n_candidates=30, candidate_fmt="run_cpd{:03d}", n_chunks=6,
                                uid=2710, start=at(S8B_DAY, 3),
                                skip=frozenset(range(1, 31)) - S8B_CRASHED)
S8B_ANALYST = 3710


@register(
    kind="negative",
    description="one scripted burst mirrors prod010.dcd + prod.coor of exactly the 21 of 30 runs that finished "
                "into selected70/<cid>/ with names and layout preserved, i.e. 'keep everything that finished'; "
                "strongest cue: machine shape (single constant-cadence burst in id order, preserved names, "
                "set = finished runs) at 70% coverage, below the cap",
    expected=ExpectedOutcome.campaign_no_selection(S8B_ROOT, cids=_names(S8B_SPEC) + _names(S8B_CRASHED_SPEC)),
    known_gap="coverage_cap: 21/30 = 70% is below the 0.8 cap and selection_confidence = 1.0*(1-21/30) = 0.30 is "
              "not < selection_conf 0.30 (the revert test is '<', not '<='), so all 21 are picked; hardening "
              "should drop a 0.5-0.8 unit that is machine-shaped (one regular burst in id order, >= 90% source "
              "names preserved, or a set equal to the finished runs) instead of nudging the boundary, which "
              "would also revert the human-shaped 70% positive twin (renames, several afternoons)",
    name="coverage_cap_70",
)
def build_coverage_cap_70() -> Inventory:
    """A COVID NAMD screen: 9 of 30 runs crash; a script keeps the final chunk and restart of the 21 that finished."""
    tb = TreeBuilder(root="/vol6")
    finished = md_campaign(tb, S8B_ROOT, S8B_SPEC)
    md_campaign(tb, S8B_ROOT, S8B_CRASHED_SPEC)
    t = at(_wd(S8B_DAY, 12), 10)
    for n, cid in enumerate(finished):
        for k, fname in enumerate(("prod010.dcd", "prod.coor")):
            tb.copy(posixpath.join(S8B_ROOT, cid, fname), posixpath.join(S8B_SELECTED, cid, fname),
                    mtime=t + 120 * n + 30 * k, uid=S8B_ANALYST)
    return tb.build()
