"""Negative group B3: copies that aren't selections.

Thesis: a copy of candidate data is evidence of a human *pick* only when it
is both a genuine subset of the candidates and not discarded. Every scenario
below lays down a real MD campaign (>= 24 candidates, >= 10 trajectory
chunks each -- the same shape the grounded positive uses) and then a
copy fingerprint that could superficially pass for a human selection: a
byte-identical backup mirror, an off-site rsync mirror, a 100%-coverage
symlink index (twice, once under an approval-sounding name), a per-run
tarball archive, copy-outs stashed only in discard directories, and a bulk
copy-out just above (and, as a documented known gap, just below) the
coverage cap. None of these are picks; the detector must still find the one
real campaign and report zero picks for it.
"""

from __future__ import annotations

import posixpath

from ..inventory import Inventory
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy,
    pick_by_symlink,
)
from . import register


def _names(spec: CampaignSpec) -> list[str]:
    """The candidate directory names ``md_campaign`` will produce for ``spec``."""
    return [spec.candidate_fmt.format(i) for i in range(1, spec.n_candidates + 1) if i not in spec.skip]


def _cp_p_mirror(tb: TreeBuilder, snap: Inventory, src_root: str, dst_root: str, *, ctime: int) -> None:
    """Recursively ``cp -p`` (or ``rsync -a``): mtimes and ownership preserved, ``ctime`` is the copy time.

    A mirrored file's content id is the *source* entry's own path, so every
    file that was not itself built from a shared "boilerplate" content id in
    the source (i.e. everything except shared per-campaign input files) gets
    the exact same sha256 as its source -- a real byte-identical copy. This
    is what a filesystem crawler would see after an actual ``cp -p -r`` or
    ``rsync -a``: same names, same tree shape, same trajectory hashes, same
    mtimes, but a fresh ctime.
    """
    src_root = src_root.rstrip("/") or "/"
    for e in snap.subtree(src_root):
        rel = e.path[len(src_root):]
        dst = dst_root if not rel else dst_root + rel
        if e.kind == "d":
            tb.dir(dst, uid=e.uid)
        elif e.kind == "f":
            tb.file(dst, size=e.size, mtime=e.mtime, uid=e.uid, content_id=e.path, ctime=ctime)
        else:
            tb.symlink(dst, e.target or "", mtime=e.mtime, uid=e.uid)


# --------------------------------------------------------------------------
# 1. Byte-identical backup mirror of the whole project (incl. analysis/)
# --------------------------------------------------------------------------

S1_PROJECT = "/vol7/projects/ABT_2012"
S1_ROOT = S1_PROJECT + "/md"
S1_BACKUP = "/vol7/backup/2012-03/ABT_2012"
S1_SPEC = CampaignSpec(engine="amber", n_candidates=24, candidate_fmt="run_lig{:03d}", n_chunks=10, uid=2101,
                       start=at(-3227, 3))
S1_ANALYST = 3101
S1_WD = 5 * (-3227 // 7)


@register(
    kind="negative",
    description="a byte-identical cp -p backup mirror of the whole project (later ctime, same mtimes, including a "
                "copy of the human analysis/ dir) under a 'backup' path must not spawn a second campaign or any "
                "picks; strongest cue is ctime ordering backed by the 'backup' path taint",
    expected=ExpectedOutcome.campaign_no_selection(S1_ROOT, cids=_names(S1_SPEC)),
    name="mirror_backup",
)
def build_mirror_backup() -> Inventory:
    """A modeller's project (campaign + generic analysis notes) is backed up byte-for-byte in March 2012."""
    tb = TreeBuilder(root="/vol7")
    md_campaign(tb, S1_ROOT, S1_SPEC)
    tb.file(posixpath.join(S1_ROOT, "submit_all.sh"), size=1_600, mtime=S1_SPEC.start - 600, uid=S1_SPEC.uid)
    human_analysis(tb, S1_PROJECT, AnalysisSpec(uid=S1_ANALYST, first_workday=S1_WD + 15))
    snap = tb.build()
    _cp_p_mirror(tb, snap, S1_PROJECT, S1_BACKUP, ctime=at(-3101, 9))
    return tb.build()


# --------------------------------------------------------------------------
# 2. rsync mirror to another volume, run dirs only, no NEG_WORDS anywhere
# --------------------------------------------------------------------------

S2_ROOT = "/vol9/site1/PROJ_2013/dock"
S2_MIRROR = "/vol9/site2/PROJ_2013/dock"
S2_SPEC = CampaignSpec(engine="gromacs", n_candidates=24, candidate_fmt="run_mol{:03d}", n_chunks=10, uid=2205,
                       start=at(-2653, 3))


@register(
    kind="negative",
    description="an rsync -a mirror of just the run directories onto a second site, same mtimes and later ctime, "
                "with no 'backup'/'old'-style taint word anywhere in its path, so the copy must be caught purely "
                "by ctime-ordered trajectory-hash overlap, not by name taint",
    expected=ExpectedOutcome.campaign_no_selection(S2_ROOT, cids=_names(S2_SPEC)),
    name="rsync_mirror",
)
def build_rsync_mirror() -> Inventory:
    """A GROMACS docking campaign is replicated to a second site for disaster recovery three months later."""
    tb = TreeBuilder(root="/vol9")
    md_campaign(tb, S2_ROOT, S2_SPEC)
    snap = tb.build()
    _cp_p_mirror(tb, snap, S2_ROOT, S2_MIRROR, ctime=at(-2562, 3))
    return tb.build()


# --------------------------------------------------------------------------
# 3. Symlink index with 100% coverage, twice, one under an approval-sounding name
# --------------------------------------------------------------------------

S3_PARENT = "/vol4/archive/PRJ_2014"
S3_ROOT = S3_PARENT + "/screen"
S3_ALL_RUNS = S3_PARENT + "/all_runs"
S3_ALL_RUNS_FINAL = S3_PARENT + "/all_runs_final"
S3_SPEC = CampaignSpec(engine="desmond", n_candidates=24, candidate_fmt="run_frag{:03d}", n_chunks=10, uid=2310,
                       start=at(-2408, 3))
S3_INDEXER = 3310


@register(
    kind="negative",
    description="two sibling symlink indexes give 100% of candidates a working-hours-created link, one of them "
                "named 'all_runs_final' to look like an approved shortlist; strongest cue is 100% coverage, which "
                "the coverage cap must drop from both directories independently",
    expected=ExpectedOutcome.campaign_no_selection(S3_ROOT, cids=_names(S3_SPEC)),
    name="symlink_index",
)
def build_symlink_index() -> Inventory:
    """A fragment-screening campaign gets a convenience symlink farm indexing every single run."""
    tb = TreeBuilder(root="/vol4")
    names = md_campaign(tb, S3_ROOT, S3_SPEC)
    pick_by_symlink(tb, dst_dir=S3_ALL_RUNS, campaign_root=S3_ROOT, cids=names, uid=S3_INDEXER,
                    mtime=at(-2317, 10), src_name="traj010.dcd", link_name="{cid}")
    pick_by_symlink(tb, dst_dir=S3_ALL_RUNS_FINAL, campaign_root=S3_ROOT, cids=names, uid=S3_INDEXER,
                    mtime=at(-2315, 11), src_name="checkpoint.chk", link_name="{cid}")
    return tb.build()


# --------------------------------------------------------------------------
# 4. Per-run tarball archive: right extension mismatch defeats derived evidence
# --------------------------------------------------------------------------

S4_PARENT = "/vol2/proj/RSV_2015"
S4_ROOT = S4_PARENT + "/simulate"
S4_ARCHIVE = S4_PARENT + "/archive"
S4_SPEC = CampaignSpec(engine="namd", n_candidates=24, candidate_fmt="run_pose{:03d}", n_chunks=10, uid=2410,
                       start=at(-2072, 3))


@register(
    kind="negative",
    description="a nightly job tars every run into archive/<cid>.tar.gz (sized like a trajectory, one 2am burst "
                "under the submitter's own uid) so the directory never reaches curated status at all (single "
                "owner, off hours, no derived-extension files, no name diversity), and even if it did, .tar.gz "
                "matches neither a copy-out hash nor a DERIVED_EXTS name, so it carries no selection evidence "
                "either way",
    expected=ExpectedOutcome.campaign_no_selection(S4_ROOT, cids=_names(S4_SPEC)),
    name="tarball_archive",
)
def build_tarball_archive() -> Inventory:
    """An automated backup job tars every NAMD run into one archive per candidate."""
    tb = TreeBuilder(root="/vol2")
    names = md_campaign(tb, S4_ROOT, S4_SPEC)
    archive_time = at(-1981, 2)
    for n, cid in enumerate(names):
        tb.file(posixpath.join(S4_ARCHIVE, f"{cid}.tar.gz"), size=S4_SPEC.chunk_size, mtime=archive_time + 30 * n,
                uid=S4_SPEC.uid)
    return tb.build()


# --------------------------------------------------------------------------
# 5. Copy-outs that exist only inside discard directories
# --------------------------------------------------------------------------

S5_ROOT = "/vol5/screens/JAK2_2016/fep"
S5_SPEC = CampaignSpec(engine="amber", n_candidates=24, candidate_fmt="run_lig{:03d}", n_chunks=10, uid=2510,
                       start=at(-1645, 3))
S5_ANALYST = 3510
S5_WD = 5 * (-1645 // 7)


@register(
    kind="negative",
    description="an analyst copies out nine different candidates but only ever into analysis/old/, bak/, trash/ "
                "and scratch/, each copy otherwise indistinguishable from a real pick (working-hours mtime, human "
                "rename, small file); strongest cue is the NEG_WORDS taint, the only thing standing between this "
                "and nine spurious picks",
    expected=ExpectedOutcome.campaign_no_selection(S5_ROOT, cids=_names(S5_SPEC)),
    name="discard_copies",
)
def build_discard_copies() -> Inventory:
    """A JAK2 FEP campaign is analysed, but every copy-out the analyst makes lands in a discard directory."""
    tb = TreeBuilder(root="/vol5")
    names = md_campaign(tb, S5_ROOT, S5_SPEC)
    analysis = human_analysis(tb, S5_ROOT, AnalysisSpec(uid=S5_ANALYST, first_workday=S5_WD + 10))
    pick_by_copy(tb, campaign_root=S5_ROOT, dst_dir=posixpath.join(analysis, "old"), cids=names[0:2],
                uid=S5_ANALYST, mtime=at(-1554, 11), rename="{id}_bestpose.nc")
    pick_by_copy(tb, campaign_root=S5_ROOT, dst_dir=posixpath.join(S5_ROOT, "bak"), cids=names[2:4],
                uid=S5_ANALYST, mtime=at(-1554, 12), rename="{id}_keep.nc")
    pick_by_copy(tb, campaign_root=S5_ROOT, dst_dir=posixpath.join(S5_ROOT, "trash"), cids=names[4:7],
                uid=S5_ANALYST, mtime=at(-1554, 13), rename="{id}_v2.nc")
    pick_by_copy(tb, campaign_root=S5_ROOT, dst_dir=posixpath.join(S5_ROOT, "scratch"), cids=names[7:9],
                uid=S5_ANALYST, mtime=at(-1554, 15), rename="{id}_check.nc")
    return tb.build()


# --------------------------------------------------------------------------
# 6. Bulk copy-out just above the coverage cap (and, as a known gap, just below)
# --------------------------------------------------------------------------

S6A_PARENT = "/vol6/hts/COVID_2017"
S6A_ROOT = S6A_PARENT + "/dock"
S6A_SELECTED = S6A_PARENT + "/selected"
S6A_SPEC = CampaignSpec(engine="gromacs", n_candidates=30, candidate_fmt="run_cpd{:03d}", n_chunks=10, uid=2610,
                        start=at(-1225, 3))
S6A_ANALYST = 3610


@register(
    kind="negative",
    description="a 'selected/' directory copies out 27 of 30 candidates (90%, above the 0.8 coverage cap) with "
                "working-hours mtimes and an approval-sounding name; strongest cue is coverage just above the cap, "
                "which an archivist would read as 'kept almost everyone', not a targeted pick",
    expected=ExpectedOutcome.campaign_no_selection(S6A_ROOT, cids=_names(S6A_SPEC)),
    name="coverage_cap_90",
)
def build_coverage_cap_90() -> Inventory:
    """A COVID docking screen: 90% of hits get copied into 'selected/', which is bulk copying, not a shortlist."""
    tb = TreeBuilder(root="/vol6")
    names = md_campaign(tb, S6A_ROOT, S6A_SPEC)
    kept = names[: round(0.9 * len(names))]
    pick_by_copy(tb, campaign_root=S6A_ROOT, dst_dir=S6A_SELECTED, cids=kept, uid=S6A_ANALYST,
                mtime=at(-1127, 10), src_name="traj010.xtc", rename="{id}_selected.xtc")
    return tb.build()


S6B_PARENT = "/vol6/hts/COVID_2018b"
S6B_ROOT = S6B_PARENT + "/dock"
S6B_SELECTED = S6B_PARENT + "/selected70"
S6B_SPEC = CampaignSpec(engine="namd", n_candidates=30, candidate_fmt="run_cpd{:03d}", n_chunks=10, uid=2710,
                        start=at(-889, 3))
S6B_ANALYST = 3710


@register(
    kind="negative",
    description="a sibling 'selected70/' directory copies out 21 of 30 candidates (70%, below the 0.8 coverage cap) "
                "with working-hours mtimes; strongest cue is coverage just below the cap -- an archivist would "
                "still call bulk-copying 70% of everyone not a targeted pick, but the detector's coverage cap does "
                "not catch it and the selection-confidence gate sits exactly on its own threshold without tripping",
    expected=ExpectedOutcome.campaign_no_selection(S6B_ROOT, cids=_names(S6B_SPEC)),
    known_gap="coverage_cap: 70% coverage is below the 0.8 cap, and mean_weight*(1-picks/n) = 1.0*(1-21/30) = 0.30 "
              "sits exactly on (not under) the 0.30 selection-confidence cutoff, so a blanket copy of 21/30 "
              "candidates with identical evidence is labelled a full selection instead of unknown/not_picked",
    name="coverage_cap_70",
)
def build_coverage_cap_70() -> Inventory:
    """Same story as coverage_cap_90 but with 70% coverage: still bulk copying, but under the detector's cap."""
    tb = TreeBuilder(root="/vol6")
    names = md_campaign(tb, S6B_ROOT, S6B_SPEC)
    kept = names[: round(0.7 * len(names))]
    pick_by_copy(tb, campaign_root=S6B_ROOT, dst_dir=S6B_SELECTED, cids=kept, uid=S6B_ANALYST,
                mtime=at(-798, 10), src_name="prod010.dcd", rename="{id}_selected.dcd")
    return tb.build()
