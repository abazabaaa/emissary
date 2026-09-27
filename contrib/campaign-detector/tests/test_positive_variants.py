"""Positive variants beyond the registry comparison: engines, replica folding, per-root binding, hooks.

These assertions hold for the underscore-id scenarios too (their known gap is
only the derived/graduation evidence), so they run unmarked.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterable

import pytest

from campaign_detector.detect import CampaignReport, DetectionResult, Evidence, EvidenceHook, Hooks, detect, is_within
from campaign_detector.inventory import Inventory
from campaign_detector.scenarios import get
from campaign_detector.scenarios import positive_amber_symlinks as sym
from campaign_detector.scenarios import positive_desmond_fep as fep
from campaign_detector.scenarios import positive_gromacs_replicates as gmx
from campaign_detector.scenarios import positive_two_campaigns as two


def _only(result: DetectionResult) -> CampaignReport:
    assert len(result.campaigns) == 1
    return result.campaigns[0]


# -- GROMACS replicates -----------------------------------------------------


@pytest.mark.parametrize("fmt, short", [(gmx.UNDERSCORE_FMT, "abl_md"), (gmx.COMPACT_FMT, "abl_md_compact_ids")])
def test_gromacs_replicas_fold_into_compounds(fmt: str, short: str) -> None:
    rep = _only(detect(get(f"positive_gromacs_replicates.{short}").build()))
    assert rep.root == gmx.ROOT
    assert rep.engine == "gromacs"
    assert rep.n_candidates == 30  # not 90: rep1..rep3 fold into their compound
    assert {c.path for c in rep.candidates} == {posixpath.join(gmx.ROOT, fmt.format(i)) for i in range(1, 31)}
    assert rep.submitter_uid == gmx.SUBMITTER
    assert rep.era == 2014


@pytest.mark.parametrize("fmt, short", [(gmx.UNDERSCORE_FMT, "abl_md"), (gmx.COMPACT_FMT, "abl_md_compact_ids")])
def test_gromacs_replica_copies_bind_to_their_compound(fmt: str, short: str) -> None:
    rep = _only(detect(get(f"positive_gromacs_replicates.{short}").build()))
    by_id = {c.id: c for c in rep.candidates}
    for i in gmx.COPIED:
        cand = by_id[fmt.format(i)]
        assert cand.label == "picked"
        (ev,) = cand.evidence
        assert ev.kind == "copy_out"
        assert ev.ref == posixpath.join(gmx.ROOT, fmt.format(i), "rep2", f"traj{gmx.N_CHUNKS:03d}.xtc")
    stray = by_id[fmt.format(gmx.DISCARDED)]
    assert stray.evidence == [] and stray.label == "not_picked"  # analysis/old is tainted


# -- Desmond FEP+ -------------------------------------------------------------


@pytest.mark.parametrize("fmt, short", [(fep.UNDERSCORE_FMT, "kdr_fep_plus"),
                                        (fep.COMPACT_FMT, "kdr_fep_plus_compact_ids")])
def test_desmond_lambda_windows_fold_into_ligands(fmt: str, short: str) -> None:
    rep = _only(detect(get(f"positive_desmond_fep.{short}").build()))
    assert rep.root == fep.ROOT
    assert rep.engine == "desmond"  # .cms/.cfg outvote NAMD's .dcd
    assert rep.n_candidates == 24  # not 288: lambda_0.00..lambda_1.00 fold into their ligand
    assert {c.id for c in rep.candidates} == {fmt.format(i) for i in range(1, 25)}
    assert rep.era == 2012


def test_desmond_graduation_adds_to_derived_but_is_weak_alone() -> None:
    rep = _only(detect(get("positive_desmond_fep.kdr_fep_plus_compact_ids").build()))
    by_id = {c.id: c for c in rep.candidates}
    graduated = by_id[fep.COMPACT_FMT.format(fep.GRADUATED)]
    assert sorted(e.kind for e in graduated.evidence) == ["derived", "graduation"]
    assert graduated.score == pytest.approx(1.2)
    follow = by_id[fep.COMPACT_FMT.format(fep.FOLLOWED_UP)]
    assert [e.kind for e in follow.evidence] == ["graduation"]
    assert follow.score == pytest.approx(0.5) and follow.label == "unknown"


INCHIKEY_BY_LIGAND = {11: "QZXKDRFEPLIGAB-UHFFFAOYSA-N", 3: "PLMNKDRFEPNOPE-UHFFFAOYSA-N"}
"""Fake ligand registry: ligand number -> InChIKey recorded at ligand prep."""
LATER_DIRS_BY_INCHIKEY = {
    "QZXKDRFEPLIGAB-UHFFFAOYSA-N": (fep.REGISTRY_DIR,),
    "PLMNKDRFEPNOPE-UHFFFAOYSA-N": ("/vol6/programs/KDR_2014/never_written",),
}
"""Fake compound index: InChIKey -> directories where that structure resurfaced."""


def _inchikey_graduation(fmt: str) -> EvidenceHook:
    """A graduation hook backed by the fake InChIKey index (for candidates named ``fmt``)."""

    def hook(inv: Inventory, report: CampaignReport) -> Iterable[Evidence]:
        for n, key in sorted(INCHIKEY_BY_LIGAND.items()):
            cid = fmt.format(n)
            for path in LATER_DIRS_BY_INCHIKEY[key]:
                entry = inv.by_path.get(path)
                if entry is not None and entry.mtime > report.t_end:  # only real, later directories count
                    yield Evidence("graduation", cid, path, key, 1.0, "InChIKey resurfaces in a later directory")

    return hook


@pytest.mark.parametrize("fmt, short", [(fep.UNDERSCORE_FMT, "kdr_fep_plus"),
                                        (fep.COMPACT_FMT, "kdr_fep_plus_compact_ids")])
def test_graduation_hook_promotes_ligand_found_by_inchikey(fmt: str, short: str) -> None:
    inv = get(f"positive_desmond_fep.{short}").build()
    lig = fmt.format(fep.FOLLOWED_UP)
    before = _only(detect(inv))
    assert lig not in before.picked()
    after = _only(detect(inv, hooks=Hooks(graduation=_inchikey_graduation(fmt))))
    assert lig in after.picked()
    cand = next(c for c in after.candidates if c.id == lig)
    hooked = [e for e in cand.evidence if e.src == fep.REGISTRY_DIR]
    assert [(e.kind, e.weight, e.ref) for e in hooked] == [("graduation", 1.0, INCHIKEY_BY_LIGAND[fep.FOLLOWED_UP])]
    # The hook's lookup for ligand 3 names a directory absent from the inventory: no evidence.
    assert all(e.src != "/vol6/programs/KDR_2014/never_written" for c in after.candidates for e in c.evidence)
    assert before.picked() <= after.picked()


# -- Amber symlink-only picks ------------------------------------------------


def test_symlink_picks_include_whole_run_dir_link() -> None:
    rep = _only(detect(get("positive_amber_symlinks.src_md").build()))
    assert rep.engine == "amber" and rep.n_candidates == 40
    assert rep.picked() == sym.PICKED
    selected = posixpath.join(sym.ROOT, "analysis", "selected_traj")
    assert selected in {d.path for d in rep.curated_dirs}
    for cid in sym.PICKED:
        cand = next(c for c in rep.candidates if c.id == cid)
        assert [e.kind for e in cand.evidence] == ["symlink"]
        assert posixpath.dirname(cand.evidence[0].src) == selected
    dir_link = next(c for c in rep.candidates if c.id == sym.DIR_LINK)
    assert dir_link.evidence[0].ref == posixpath.join(sym.ROOT, sym.DIR_LINK)


# -- Two campaigns in one project --------------------------------------------


def test_two_campaigns_bind_picks_to_their_own_root() -> None:
    result = detect(get("positive_two_campaigns.project_with_two").build())
    reports = {r.root: r for r in result.campaigns}
    assert set(reports) == {two.FEP_ROOT, two.MD_ROOT}
    fep_rep, md_rep = reports[two.FEP_ROOT], reports[two.MD_ROOT]
    assert (fep_rep.engine, fep_rep.n_candidates, fep_rep.submitter_uid) == ("amber", 30, two.FEP_SPEC.uid)
    assert (md_rep.engine, md_rep.n_candidates, md_rep.submitter_uid) == ("namd", 20, two.MD_SPEC.uid)
    assert fep_rep.picked() == {*two.FEP_COPIED, two.FEP_PLOTTED}
    assert md_rep.picked() == set(two.MD_COPIED)
    shared = posixpath.join(two.PROJECT, "analysis")
    for rep in (fep_rep, md_rep):
        assert [d.path for d in rep.curated_dirs] == [shared]
        for c in rep.candidates:
            assert all(is_within(e.ref, rep.root) and posixpath.dirname(e.src) == shared for e in c.evidence)
    md_copy_names = {posixpath.basename(e.src) for c in md_rep.candidates for e in c.evidence}
    assert md_copy_names == {f"{cid}_holo_final.dcd" for cid in two.MD_COPIED}
    assert not md_copy_names & {posixpath.basename(e.src) for c in fep_rep.candidates for e in c.evidence}
