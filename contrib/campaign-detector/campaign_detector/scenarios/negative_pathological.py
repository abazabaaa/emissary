"""Negative group B6 -- structural pathologies.

Thesis of the group: odd directory *shapes* must neither crash the detector
nor be misread as a campaign with a selection. Each scenario removes exactly
one thing a real campaign needs (siblings, a single-submitter batch, headcount
of *candidates*, structure, MD file classes, or a link that resolves into a
candidate) while looking superficially plausible, and most carry a genuine
human "pick" so that a false campaign would also produce a false selection.

The positive twins that sit on the other side of each boundary live in
:mod:`positive_pathological_links`.

Adversarial review
------------------
Changed: three of the writer's cases encoded judgement calls against the
archivist's answer and were moved to the positive module with honest
expectations -- the 10-hop symlink chain into one candidate (a pick to any
human who follows it), the four same-uid AMBER runs among 26 unrelated
``proj_###`` dirs (a small campaign by the content rule below) and a
depth-30 variant with four sibling runs (depth must never block detection).
Their negative twins here are now honest: ``symlink_pathology`` keeps the
loops and dangling links but its long chain ends in a *dangling* path and a
second chain loops, and ``numbered_siblings_heterogeneous`` spreads its MD
runs across five uids and five years, which no archivist calls one
campaign. Added ``few_candidates_replicated`` (3 ligands x 4 replicas: the
replica dirs are not candidates -- this one fools the detector, see its
``known_gap``) and ``dated_meeting_notes_with_structures`` (meeting notes
with an attached multi-model PDB and assay CSV). ``deep_chain_arbitrary``
now carries a real copy-out of its lone run, so only the missing siblings
stand between it and a positive.

Rule adopted for grouping: a campaign is a batch of at least
``min_candidates`` run directories under one parent with the same file
signature, one submitter and overlapping run times; the name template is
evidence of such a batch, not its definition. So four co-submitted runs
remain a campaign even when their names share a template with unrelated
folders (positive, known gap), while MD runs by different people in
different years under one numbering scheme are not (negative, here).

Tried and could not break: loops, self-links, links above ``/``, dangling
links and links to the campaign root never produced symlink evidence or an
exception; one-hop resolution uses path components, so a dangling link to
a never-run ``run_cpd007`` is not credited to any real candidate; a flat
directory of 3,000 files, a 30-deep chain and 10 uniform meeting folders
with chemistry attachments never became a root.
"""

from __future__ import annotations

import posixpath

from ..inventory import Inventory
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy,
    workday,
)
from . import register

# --------------------------------------------------------------------------
# 1. Deep single chains: never enough siblings to reach min_candidates.
# --------------------------------------------------------------------------

ARBITRARY_SEGMENTS = tuple(chr(ord("a") + i) for i in range(26)) + ("aa", "bb", "cc", "dd")
"""30 distinct, non-digit path segments: /vol1/a/b/c/.../z/aa/bb/cc/dd."""

TEMPLATED_SEGMENTS = tuple(f"level{i:02d}" for i in range(1, 31))
"""30 nested, digit-templated segments, still exactly one child per level."""


@register(
    kind="negative",
    description=(
        "One AMBER run at the bottom of a 30-level chain of hand-named one-child dirs, copied out by an "
        "analyst, is a lone job and not a campaign; strongest cue: no directory on the path has a sibling."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_deep_chain_arbitrary() -> Inventory:
    """One AMBER run at the bottom of a 30-deep chain of one-child directories, with a real copy-out."""
    tb = TreeBuilder(root="/vol1")
    bottom = "/vol1/" + "/".join(ARBITRARY_SEGMENTS)
    names = md_campaign(tb, bottom, CampaignSpec(engine="amber", n_candidates=1, candidate_fmt="lone_run",
                                                 n_chunks=5, uid=1101, start=at(0, 3)))
    analysis = human_analysis(tb, "/vol1/results", AnalysisSpec(uid=1501, first_workday=20, dirname="final"))
    pick_by_copy(tb, bottom, analysis, names, src_name="prod005.nc", rename="lone_best.nc", uid=1501,
                 mtime=at(workday(21), 11))
    return tb.build()


@register(
    kind="negative",
    description=(
        "One AMBER run at the bottom of a 30-deep chain of machine-templated one-child dirs "
        "(level01/level02/...) is still a lone job; strongest cue: a templated name never creates siblings."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_deep_chain_templated() -> Inventory:
    """One AMBER run at the bottom of a 30-deep chain of templated one-child directories.

    Its twin ``positive_pathological_links.deep_chain_campaign`` puts four sibling runs at the
    same depth and must be found.
    """
    tb = TreeBuilder(root="/vol7")
    bottom = "/vol7/" + "/".join(TEMPLATED_SEGMENTS)
    md_campaign(tb, bottom, CampaignSpec(engine="amber", n_candidates=1, candidate_fmt="run01", n_chunks=5,
                                         uid=1201, start=at(0, 3)))
    return tb.build()


# --------------------------------------------------------------------------
# 2. Numbered siblings, heterogeneous contents and no single-submitter batch.
# --------------------------------------------------------------------------

PROJ_ROOT = "/vol2/archive/proj_pool"

_DOCKING_FILES = ("vina_out.pdbqt", "receptor.pdb", "poses.sdf", "scores.csv")
_SHEET_FILES = ("dG_summary.xlsx", "raw_data.csv")
_PHOTO_FILES = ("img001.jpg", "img002.jpg", "poster.png")
_NOTE_FILES = ("readme.txt",)
_MIXED_FILES = ("scratch.log", "plan.md")
MISC_PATTERNS = (_DOCKING_FILES, _SHEET_FILES, _PHOTO_FILES, _NOTE_FILES, _MIXED_FILES)
"""File sets of the non-MD project folders (shared with the positive twin)."""

SOLO_MD = {3: 2203, 9: 2209, 14: 2214, 21: 2221, 27: 2227}
"""proj index -> uid of the one person who ran one AMBER job in that folder."""


def misc_project(tb: TreeBuilder, root: str, i: int) -> None:
    """Fill ``root/proj_<i>`` with one of the non-MD file sets, written by uid 2100+i in quarter i."""
    d = f"{root}/proj_{i:03d}"
    pattern = MISC_PATTERNS[i % len(MISC_PATTERNS)]
    mtime = at(i * 91, 10)
    for n, name in enumerate(pattern):
        tb.file(f"{d}/{name}", size=2_000 + n * 500, mtime=mtime + n * 60, uid=2100 + i)


@register(
    kind="negative",
    description=(
        "30 proj_### folders where five hold one AMBER run each by five different people in five different "
        "years (and an analyst copied one out) are a project pool, not a campaign; strongest cue: the "
        "MD-bearing folders share no submitter and no time window, so no batch exists to isolate."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_numbered_siblings_heterogeneous() -> Inventory:
    """Five solo AMBER runs (distinct uids, ~one year apart) among 25 non-MD project folders.

    Even a detector that isolated same-signature subsets inside a template group (the fix for
    ``positive_pathological_links.numbered_siblings_md_subset``) must still reject this: the
    subset's uid purity is 0.2 and its runs are years apart.
    """
    tb = TreeBuilder(root="/vol2")
    for i in range(1, 31):
        if i in SOLO_MD:
            md_campaign(tb, PROJ_ROOT, CampaignSpec(
                engine="amber", n_candidates=1, candidate_fmt=f"proj_{i:03d}", n_chunks=6, uid=SOLO_MD[i],
                start=at(i * 70, 3)))
        else:
            misc_project(tb, PROJ_ROOT, i)
    tb.dir(PROJ_ROOT, uid=2100)
    review = human_analysis(tb, "/vol2/archive", AnalysisSpec(uid=2901, first_workday=1500, dirname="md_highlights"))
    pick_by_copy(tb, PROJ_ROOT, review, ["proj_014"], src_name="prod006.nc", rename="proj014_final.nc", uid=2901,
                 mtime=at(workday(1501), 14))
    return tb.build()


# --------------------------------------------------------------------------
# 3. Below min_candidates, even with a real human pick.
# --------------------------------------------------------------------------

TINY_ROOT = "/vol4/legacy/tiny_campaign/data"
TINY_SPEC = CampaignSpec(engine="amber", n_candidates=3, candidate_fmt="run_x{:03d}", n_chunks=6, uid=9001,
                         start=at(500, 3))
"""Three AMBER runs; ``positive_pathological_links.four_candidates_boundary`` uses four."""


def tiny_campaign(tb: TreeBuilder, root: str, spec: CampaignSpec) -> None:
    """Lay down ``spec`` under ``root`` plus an analysis/ that copies out the first candidate."""
    names = md_campaign(tb, root, spec)
    analysis = human_analysis(tb, root, AnalysisSpec(uid=9501, first_workday=600, bursts=2))
    src = "prod001.nc" if spec.inner_fmt is None else posixpath.join(spec.inner_fmt.format(1), "prod001.nc")
    pick_by_copy(tb, root, analysis, names[:1], src_name=src, uid=9501, mtime=at(workday(600), 11))


@register(
    kind="negative",
    description=(
        "Three AMBER runs with a genuine copy-out pick are a tiny study below the documented campaign "
        "size; strongest cue: 3 candidates, one short of min_candidates=4."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_few_candidates_with_pick() -> Inventory:
    """3 AMBER runs plus a real copy-out pick; the boundary twin with 4 runs is a positive.

    The detector's rule is a hard floor on candidate count (README: min_candidates=4); an archivist
    would call this a tiny study with a pick, and the floor exists because three dirs are too few to
    tell a script's batch from a person's three manual runs.
    """
    tb = TreeBuilder(root="/vol4")
    tiny_campaign(tb, TINY_ROOT, TINY_SPEC)
    return tb.build()


REPL_ROOT = "/vol4/legacy/tiny_replicas/data"


@register(
    kind="negative",
    description=(
        "Three ligands run in four replicas each (run_x001/rep1..rep4, with a copy-out of one replica's "
        "chunk) are still three candidates below the campaign floor; strongest cue: replica dirs fold into "
        "their ligand and are never candidates themselves."
    ),
    expected=ExpectedOutcome.no_campaign(),
    known_gap=("campaign_root: each run_x00N with four rep# children qualifies as its own root, and the parent "
               "has only 3 candidates so nothing absorbs them; the replicas are reported as candidates of three "
               "separate campaigns and the copied replica is 'picked'"),
)
def build_few_candidates_replicated() -> Inventory:
    """3 candidates x 4 replicas, a copy-out of ``run_x001/rep1/prod001.nc``.

    Replicas are repeats of one candidate, not alternatives a human chooses between, so the honest
    candidate count is 3 and the documented floor says no campaign.
    """
    tb = TreeBuilder(root="/vol4")
    tiny_campaign(tb, REPL_ROOT, CampaignSpec(engine="amber", n_candidates=3, candidate_fmt="run_x{:03d}",
                                              inner_fmt="rep{}", n_inner=4, n_chunks=6, uid=9001, start=at(500, 3)))
    return tb.build()


# --------------------------------------------------------------------------
# 4. Huge flat mixed directory: no subdirectories at all.
# --------------------------------------------------------------------------

FLAT_ROOT = "/vol6/dump/raw"
_FLAT_EXTS = (".nc", ".prmtop", ".png", ".pdf", ".xlsx", ".txt", ".csv", ".dcd", ".log")
_FLAT_UIDS = tuple(range(6001, 6021))


def flat_dump(tb: TreeBuilder, root: str = FLAT_ROOT, n: int = 3000) -> None:
    """``n`` mixed files (MD-looking ones included) from 20 uids over ~8 years, directly in ``root``."""
    for i in range(n):
        ext = _FLAT_EXTS[i % len(_FLAT_EXTS)]
        uid = _FLAT_UIDS[i % len(_FLAT_UIDS)]
        day = (i * 37) % (365 * 8)  # deterministic spread across roughly 8 years
        tb.file(f"{root}/file_{i:05d}{ext}", size=1_024 + (i % 50) * 997, mtime=at(day, 9 + (i % 8)), uid=uid)


@register(
    kind="negative",
    description=(
        "One flat directory of 3,000 mixed files (trajectory, topology and log extensions included) from "
        "20 uids over eight years is a dump, not a campaign; strongest cue: zero subdirectories, so there "
        "is no sibling group to evaluate."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_huge_flat_mixed() -> Inventory:
    """A single directory of 3,000 mixed files and no subdirectories."""
    tb = TreeBuilder(root="/vol6")
    flat_dump(tb)
    return tb.build()


# --------------------------------------------------------------------------
# 5. Uniform, templated, but zero MD file classes.
# --------------------------------------------------------------------------

NOTES_ROOT = "/vol8/shared/meeting_notes"
MEETING_DATES = ("2011-03-04", "2011-03-11", "2011-03-18", "2011-03-25", "2011-04-01",
                 "2011-04-08", "2011-04-15", "2011-04-22", "2011-04-29", "2011-05-06")


def meeting_notes(tb: TreeBuilder, root: str, attachments: bool) -> None:
    """Ten weekly meeting folders; ``attachments`` adds a multi-model PDB and an assay CSV to each."""
    for i, date in enumerate(MEETING_DATES):
        d = f"{root}/{date}"
        mtime = at(400 + i * 7, 14)
        tb.file(f"{d}/notes.txt", size=3_000, mtime=mtime, uid=8001)
        tb.file(f"{d}/agenda.docx", size=15_000, mtime=mtime - 3600, uid=8001)
        tb.file(f"{d}/slides.pptx", size=500_000, mtime=mtime + 1800, uid=8001)
        if attachments:
            tb.file(f"{d}/complex_frames.pdb", size=40_000_000, mtime=mtime - 1800, uid=8001)
            tb.file(f"{d}/ic50.csv", size=6_000, mtime=mtime - 1200, uid=8001)


@register(
    kind="negative",
    description=(
        "Ten date-named meeting folders, perfectly uniform (notes, agenda, slides) and written by one uid, "
        "are minutes, not runs; strongest cue: zero MD file classes."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_dated_meeting_notes() -> Inventory:
    """10 weekly meeting-notes directories, uniform but entirely non-MD content."""
    tb = TreeBuilder(root="/vol8")
    meeting_notes(tb, NOTES_ROOT, attachments=False)
    return tb.build()


@register(
    kind="negative",
    description=(
        "The same meeting folders each carrying a 40 MB multi-model complex PDB and an IC50 CSV (structures "
        "attached for discussion) are still minutes; strongest cue: structures are not trajectories -- no "
        "TRAJ class, no chunk series, no topology or restart."
    ),
    expected=ExpectedOutcome.no_campaign(),
)
def build_dated_meeting_notes_with_structures() -> Inventory:
    """10 uniform meeting folders whose bytes are dominated by attached PDB structures."""
    tb = TreeBuilder(root="/vol8")
    meeting_notes(tb, "/vol8/shared/project_meetings", attachments=True)
    return tb.build()


# --------------------------------------------------------------------------
# 6. Symlink loops, self-references, dangling links, a dangling chain and a looping chain.
# --------------------------------------------------------------------------

GPCR_ROOT = "/vol5/projects/GPCR_2012/screen"
GPCR_SPEC = CampaignSpec(engine="amber", n_candidates=6, candidate_fmt="run_cpd{:03d}", n_chunks=8, uid=7001,
                         start=at(200, 3))
"""A real 6-candidate campaign shared with ``positive_pathological_links.symlink_chain_pick``."""


def link_chain(tb: TreeBuilder, farm: str, final_target: str, hops: int, *, uid: int, mtime: int) -> str:
    """``hops - 1`` symlinks ``farm/hNN/link`` chained towards ``final_target``; returns the head hop.

    Each hop sits alone in its own directory, so no intermediate hop is a direct child of a curated
    directory. The caller adds the last hop (the one a human sees) pointing at the returned path.
    """
    prev = final_target
    for n in range(hops, 1, -1):
        hop = f"{farm}/h{n:02d}/link"
        tb.symlink(hop, prev, mtime=mtime, uid=uid)
        prev = hop
    return prev


@register(
    kind="negative",
    description=(
        "A real 6-candidate campaign whose analysis/ holds only broken links (self-loop, a looping chain, a "
        "10-hop chain ending at never-run run_cpd007, links above / and to the campaign root) has no pick; "
        "strongest cue: none of those links resolves into an existing candidate."
    ),
    expected=ExpectedOutcome.campaign_no_selection(GPCR_ROOT, cids=[f"run_cpd{i:03d}" for i in range(1, 7)]),
)
def build_symlink_pathology() -> Inventory:
    """A real campaign plus symlink loops/self-refs/dangling links; nothing resolves to a candidate.

    ``analysis/legacy_link`` starts a 10-symlink chain ending at ``run_cpd007/prod001.nc`` -- the
    campaign has six candidates, so that path never existed and even a detector that followed chains
    must not credit it to any candidate. ``analysis/loop_link`` enters a three-link cycle. The
    positive twin (the same chain ending inside ``run_cpd003``) is
    ``positive_pathological_links.symlink_chain_pick``.
    """
    tb = TreeBuilder(root="/vol5")
    md_campaign(tb, GPCR_ROOT, GPCR_SPEC)
    analysis = human_analysis(tb, GPCR_ROOT, AnalysisSpec(uid=7501, first_workday=300, bursts=3))
    t = at(workday(300), 11)

    # Pathological links outside any curated dir.
    tb.symlink("/vol5/misc/a/loop", "../a", mtime=at(190, 0), uid=7001)
    tb.symlink("/vol5/misc/b/self", ".", mtime=at(190, 0), uid=7001)
    tb.symlink("/vol5/misc/dangling1", "/vol5/nowhere/ghost1.nc", mtime=at(190, 0), uid=7001)
    tb.symlink("/vol5/misc/dangling2", "/vol5/also_missing/ghost2.rst7", mtime=at(190, 0), uid=7001)

    # Inside the curated dir, where the detector does resolve links.
    tb.symlink(posixpath.join(analysis, "self_link"), "self_link", mtime=t, uid=7501)
    tb.symlink(posixpath.join(analysis, "whole_screen"), "..", mtime=t, uid=7501)
    tb.symlink(posixpath.join(analysis, "escape"), "../" * 12 + "etc", mtime=t, uid=7501)
    tb.symlink(posixpath.join(analysis, "never_ran"), "../run_cpd007/prod001.nc", mtime=t, uid=7501)
    dangling = posixpath.join(GPCR_ROOT, "run_cpd007", "prod001.nc")
    head = link_chain(tb, "/vol5/linkfarm", dangling, 10, uid=7501, mtime=at(workday(300), 9))
    tb.symlink(posixpath.join(analysis, "legacy_link"), head, mtime=t, uid=7501)
    tb.symlink("/vol5/loopfarm/l1/link", "/vol5/loopfarm/l2/link", mtime=t, uid=7501)
    tb.symlink("/vol5/loopfarm/l2/link", "/vol5/loopfarm/l3/link", mtime=t, uid=7501)
    tb.symlink("/vol5/loopfarm/l3/link", "/vol5/loopfarm/l1/link", mtime=t, uid=7501)
    tb.symlink(posixpath.join(analysis, "loop_link"), "/vol5/loopfarm/l1/link", mtime=t, uid=7501)
    return tb.build()
