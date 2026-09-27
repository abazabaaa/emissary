"""Two-pass detection with content: graduation and mention hooks, identity scenarios, winner rows, CLI."""

from __future__ import annotations

import dataclasses
import posixpath
from pathlib import Path

import pytest

from campaign_detector.content import sidecar
from campaign_detector.content.__main__ import main as content_main
from campaign_detector.content.fake import fake_registry
from campaign_detector.content.graduation import GraduationIndex
from campaign_detector.content.model import read_tsv
from campaign_detector.content.pipeline import ContentRun, detect_with_content, loose_refs, run_content
from campaign_detector.content.sidecar import SidecarBuilder, fake_inchikey
from campaign_detector.content.winner import (
    BASE_COLUMNS, EXCLUDED_COLUMNS, is_leakage_metric, winner_columns, winner_rows, write_winner_tsv,
)
from campaign_detector.detect import detect
from campaign_detector.inventory import Inventory
from campaign_detector.scenarios import all_scenarios, get
from campaign_detector.scenarios import positive_identity_graduation as pig
from campaign_detector.synth import TreeBuilder, at, compare, md_campaign, workday

KDR = pig.KDR_ROOT
ABL = pig.ABL_ROOT


def _run(inv: Inventory, sb: SidecarBuilder, tmp: Path) -> ContentRun:
    sidecar.write(sb, tmp, inv=inv)
    return run_content(inv, fake_registry(tmp))


def _scenario_run(name: str, tmp: Path) -> ContentRun:
    s = get(name)
    inv = s.build()
    sidecar.write(s, tmp, inv=inv)
    return run_content(inv, fake_registry(tmp))


def _kdr(tb: TreeBuilder | None = None) -> tuple[TreeBuilder, SidecarBuilder, str]:
    tb = tb or TreeBuilder(root="/vol3")
    sb = SidecarBuilder()
    analysis = pig.kdr_campaign(tb, sb)
    return tb, sb, analysis


def _report(run: ContentRun, root: str):  # type: ignore[no-untyped-def]
    return next(r for r in run.result.campaigns if r.root == root)


# --------------------------------------------------------------------------
# identity scenarios: inventory-only vs content answers
# --------------------------------------------------------------------------


@pytest.mark.parametrize("short", sorted(pig.CONTENT_EXPECTED))
def test_identity_graduation_content_answer(short: str, tmp_path: Path) -> None:
    run = _scenario_run(f"positive_identity_graduation.{short}", tmp_path)
    assert compare(pig.CONTENT_EXPECTED[short], run.result) == []
    lig029 = next(c for c in _report(run, KDR).candidates if c.id == "run_lig029")
    (ev,) = [e for e in lig029.evidence if e.kind == "graduation"]
    assert ev.src == f"{ABL}/cpd03/cpd03.mol2" and ev.weight == 1.0
    assert ev.ref == f"{fake_inchikey(pig.kdr_smiles(29))} {ABL}::cpd03"


def test_identity_graduation_inventory_only_answer_is_the_documented_split() -> None:
    base = get("positive_identity_graduation.kdr_then_abl")
    assert base.known_gap and base.known_gap.startswith("graduation:")
    plain = detect(base.build())
    assert _picked(plain) == {KDR: set(), ABL: set()}
    variant = get("positive_identity_graduation.kdr_then_abl_copyout")
    assert variant.known_gap is None
    assert compare(variant.expected, detect(variant.build())) == []


def _picked(result) -> dict[str, set[str]]:  # type: ignore[no-untyped-def]
    return {r.root: r.picked() for r in result.campaigns}


def test_text_mention_picks_lig035_from_curated_notes(tmp_path: Path) -> None:
    run = _scenario_run("positive_identity_graduation.kdr_then_abl_copyout", tmp_path)
    lig035 = next(c for c in _report(run, KDR).candidates if c.id == "run_lig035")
    assert [(e.kind, e.src, e.ref, e.weight) for e in lig035.evidence] == [
        ("text_mention", f"{KDR}/analysis/notes.txt", "lig035", 0.7)]


@pytest.mark.parametrize("short", ["rerun_all", "in_backup", "earlier"])
def test_identity_negatives_have_no_picks_with_content(short: str, tmp_path: Path) -> None:
    s = get(f"negative_identity.{short}")
    run = _scenario_run(s.name, tmp_path)
    assert compare(s.expected, run.result) == []
    assert all(not r.picked() for r in run.result.campaigns)
    assert all(not c.evidence for r in run.result.campaigns for c in r.candidates)


def test_rerun_all_is_dropped_by_the_coverage_cap(tmp_path: Path) -> None:
    run = _scenario_run("negative_identity.rerun_all", tmp_path)
    kdr = _report(run, KDR)
    assert any("dropped 46 graduation links from /vol6/projects/KDR_rerun_2014/md" in n for n in kdr.notes)


def test_backup_occurrences_are_indexed_but_tainted(tmp_path: Path) -> None:
    run = _scenario_run("negative_identity.in_backup", tmp_path)
    occ = run.graduation.lookup(fake_inchikey(pig.kdr_smiles(29)))
    paths = {o.path for o in occ}
    assert "/vol7/backup/registry_2013/kdr_nominations.sdf" in paths
    assert "/vol5/projects/ABL_2013/bak/from_kdr.sdf" in paths
    inv = get("negative_identity.in_backup").build()
    assert run.graduation.evidence(inv, _report(run, KDR)) == []


def test_earlier_occurrences_are_origins_not_graduations(tmp_path: Path) -> None:
    run = _scenario_run("negative_identity.earlier", tmp_path)
    occ = run.graduation.lookup(fake_inchikey(pig.kdr_smiles(29)))
    assert [o.path for o in occ][0] == "/vol2/docking/KDR_2009/fred_hits.sdf"
    pilot = _report(run, "/vol2/projects/KDR_pilot_2009/md")
    assert any(f"dropped 8 graduation links from {KDR}" in n for n in pilot.notes)


# --------------------------------------------------------------------------
# hooks on hand-built variations
# --------------------------------------------------------------------------


def test_registry_row_later_is_strong_and_stereo_variant_is_weak(tmp_path: Path) -> None:
    tb, sb, _ = _kdr()
    later = at(7 * (pig.WEEK + 60), 11)
    export = tb.file("/vol9/registry/exports/nominations_2012.sdf", size=9_000, mtime=later, uid=3002)
    sb.ligand(export, pig.kdr_smiles(12), name=pig.kdr_compound(12), record="1")
    variant = pig.kdr_smiles(20).replace("N", "N/", 1)
    sb.ligand(export, variant, name="REG-20-iso", record="2")
    sb.ligand(export, pig.kdr_smiles(30), name="REG-30", confidence="low", record="3")
    run = _run(tb.build(), sb, tmp_path)
    by_id = {c.id: c for c in _report(run, KDR).candidates}
    assert _report(run, KDR).picked() == {"run_lig012"}
    assert [(e.src, e.weight) for e in by_id["run_lig012"].evidence] == [(export, 1.0)]
    assert [e.weight for e in by_id["run_lig020"].evidence] == [0.5], "connectivity-block match is weak"
    assert "connectivity block" in by_id["run_lig020"].evidence[0].note
    assert [e.weight for e in by_id["run_lig030"].evidence] == [0.5], "low confidence is weak"
    assert by_id["run_lig020"].label == by_id["run_lig030"].label == "unknown", "0.5 < pick threshold"


def test_weak_matches_never_add_up_to_a_pick(tmp_path: Path) -> None:
    tb, sb, _ = _kdr()
    variant = pig.kdr_smiles(12).replace("N", "N/", 1)
    for n in range(3):
        f = tb.file(f"/vol9/registry/exports/n{n}.sdf", size=900, mtime=at(7 * (pig.WEEK + 60 + n), 11), uid=3002)
        sb.ligand(f, variant, name=f"REG-{n}")
    run = _run(tb.build(), sb, tmp_path)
    lig012 = next(c for c in _report(run, KDR).candidates if c.id == "run_lig012")
    assert [(e.src, e.weight) for e in lig012.evidence] == [("/vol9/registry/exports/n0.sdf", 0.5)]
    assert not _report(run, KDR).picked()


def test_copy_into_a_later_campaign_graduates(tmp_path: Path) -> None:
    tb = TreeBuilder(root="/vol3")
    sb = SidecarBuilder()
    pig.kdr_campaign(tb, sb)
    md_campaign(tb, ABL, pig.ABL_SPEC)
    for j in range(1, 9):
        mol2 = f"{ABL}/cpd{j:02d}/cpd{j:02d}.mol2"
        if j == 3:  # cp -p of KDR's antechamber file: the FakeReader finds its facts by sha256
            tb.copy(f"{KDR}/run_lig029/lig029.mol2", mol2, mtime=pig.ABL_SPEC.start - 7200, uid=2005)
        else:
            sb.ligand(tb.file(mol2, size=6_000, mtime=pig.ABL_SPEC.start - 7200, uid=2005),
                      pig.other_smiles("abl", j))
    cpd03 = f"{ABL}/cpd03/cpd03.mol2"
    inv = tb.build()
    assert inv.by_path[cpd03].sha256 == inv.by_path[f"{KDR}/run_lig029/lig029.mol2"].sha256
    run = _run(inv, sb, tmp_path)
    assert _report(run, KDR).picked() == {"run_lig029"}


def test_missing_inchikey14_falls_back_to_the_key_block(tmp_path: Path) -> None:
    run = _scenario_run("positive_identity_graduation.kdr_then_abl", tmp_path)
    contents = dict(run.contents)
    abl = contents[f"{ABL}::cpd03"]
    variant = fake_inchikey(pig.kdr_smiles(29).replace("N", "N/", 1))
    contents[abl.key] = dataclasses.replace(abl, ligands=[dataclasses.replace(
        lig, inchikey=variant, inchikey14=None) for lig in abl.ligands])
    inv = get("positive_identity_graduation.kdr_then_abl").build()
    index = GraduationIndex.build(inv, run.first_pass, contents, [])
    evs = index.evidence(inv, _report(run, KDR))
    assert [(e.candidate, e.weight) for e in evs] == [("run_lig029", 0.5)]


def test_earlier_registry_row_and_byte_copies_are_not_graduation(tmp_path: Path) -> None:
    tb, sb, _ = _kdr()
    earlier = tb.file("/vol9/registry/exports/nominations_2010.sdf", size=9_000,
                      mtime=at(7 * (pig.WEEK - 20), 11), uid=3002)
    sb.ligand(earlier, pig.kdr_smiles(12), name=pig.kdr_compound(12))
    tb.copy(f"{KDR}/run_lig029/lig029.mol2", "/vol9/share/lig029.mol2", mtime=at(7 * (pig.WEEK + 60), 9))
    inv = tb.build()
    run = _run(inv, sb, tmp_path)
    assert any(o.path == "/vol9/share/lig029.mol2" for o in run.graduation.lookup(fake_inchikey(pig.kdr_smiles(29))))
    assert all(not c.evidence for c in _report(run, KDR).candidates)


def test_mentions_need_a_curated_dir_and_match_compound_ids_and_keys(tmp_path: Path) -> None:
    tb, sb, analysis = _kdr()
    sb.mention(posixpath.join(analysis, "README.md"), "KDR-0877", "compound_id")
    sb.mention(posixpath.join(analysis, "dG_summary_v3.xlsx"), fake_inchikey(pig.kdr_smiles(7)), "inchikey")
    stray = tb.file("/vol9/misc/scratchpad_notes.txt", size=100, mtime=at(workday(pig.WD + 30), 10), uid=3002)
    sb.mention(stray, "lig044", "candidate_id")
    run = _run(tb.build(), sb, tmp_path)
    kdr = _report(run, KDR)
    assert kdr.picked() == {"run_lig029", "run_lig007"}
    assert {e.kind for c in kdr.candidates for e in c.evidence} == {"text_mention"}


def test_mentions_of_every_candidate_are_capped(tmp_path: Path) -> None:
    tb, sb, analysis = _kdr()
    for i in pig.spec_indices(pig.KDR_SPEC):
        sb.mention(posixpath.join(analysis, "notes.txt"), f"lig{i:03d}")
    run = _run(tb.build(), sb, tmp_path)
    kdr = _report(run, KDR)
    assert not kdr.picked()
    assert any("text_mention links" in n for n in kdr.notes)


# --------------------------------------------------------------------------
# pipeline invariants
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", [s.name for s in all_scenarios()])
def test_without_sidecar_facts_content_detection_equals_plain_detection(name: str) -> None:
    inv = get(name).build()
    assert detect_with_content(inv, None).to_dict() == detect(inv).to_dict()


def test_pipeline_is_deterministic(tmp_path: Path) -> None:
    a = _scenario_run("positive_identity_graduation.kdr_then_abl_copyout", tmp_path / "a")
    b = _scenario_run("positive_identity_graduation.kdr_then_abl_copyout", tmp_path / "b")
    assert a.result.to_dict() == b.result.to_dict()
    assert winner_rows(a.result, a.contents, records=a.records) == winner_rows(b.result, b.contents, records=b.records)


def test_loose_refs_exclude_candidate_files_and_md_classes() -> None:
    s = get("positive_identity_graduation.kdr_then_abl_copyout")
    inv = s.build()
    run = run_content(inv, fake_registry(None))
    refs = loose_refs(inv, run.records)
    paths = {r.path for r in refs}
    assert f"{KDR}/analysis/notes.txt" in paths
    assert not any(p.startswith(f"{KDR}/run_lig") for p in paths)
    assert not any(p.endswith(".nc") for p in paths), "copied trajectories are not loose content"


# --------------------------------------------------------------------------
# winner rows
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def winner_run(tmp_path_factory: pytest.TempPathFactory) -> ContentRun:
    tb, sb = pig.scene(True)
    analysis = f"{KDR}/analysis"
    sb.metric(f"{analysis}/dG_summary_v3.xlsx", "analyst_rank", 1.0, scope="node")
    sb.metric(f"{KDR}/run_lig012/ti_summary.csv", "exp_ic50", 12.0, "nM", scope="node")
    return _run(tb.build(), sb, tmp_path_factory.mktemp("winner"))


def test_winner_rows_exclude_leakage_columns(winner_run: ContentRun) -> None:
    rows = winner_rows(winner_run.result, winner_run.contents, records=winner_run.records)
    cols = list(rows[0])
    assert cols[: len(BASE_COLUMNS)] == list(BASE_COLUMNS)
    assert not EXCLUDED_COLUMNS & set(cols)
    for banned in ("exp_dg", "content_exp_dg", "content_exp_ic50", "score", "evidence", "selection_confidence",
                   "content_analyst_rank"):
        assert banned not in cols
    assert not any("exp_" in c or "curated" in c or "analyst" in c for c in cols)
    assert {"content_dg_pred", "content_dg_unc", "content_sim_time_ns", "meta_traj_chunk_count",
            "meta_submit_rank", "meta_n_sched"} <= set(cols)
    assert is_leakage_metric("exp_dg") and is_leakage_metric("EXP_pIC50") and not is_leakage_metric("dg_pred")
    with pytest.raises(ValueError):
        winner_columns([{"key": "k", "score": 1.0}])


def test_winner_rows_carry_labels_and_identity(winner_run: ContentRun) -> None:
    rows = {r["key"]: r for r in winner_rows(winner_run.result, winner_run.contents, records=winner_run.records)}
    assert len(rows) == 46 + 8
    labels = {f"{rep.root}::{c.id}": c.label for rep in winner_run.result.campaigns for c in rep.candidates}
    assert {k: r["label"] for k, r in rows.items()} == labels
    lig029 = rows[f"{KDR}::run_lig029"]
    assert lig029["label"] == "picked" and lig029["inchikey"] == fake_inchikey(pig.kdr_smiles(29))
    assert lig029["inchikey14"] == fake_inchikey(pig.kdr_smiles(29))[:14] and lig029["unit"] == "ligand"
    assert lig029["meta_traj_chunk_count"] == 20 and lig029["meta_n_traj_files"] == 20
    abl = rows[f"{ABL}::cpd01"]
    assert abl["label"] == "unknown" and abl["content_dg_pred"] is None
    trimmed = winner_rows(winner_run.result, winner_run.contents, include_unknown=False)
    assert all(r["label"] != "unknown" for r in trimmed) and len(trimmed) == 46


def test_winner_tsv_round_trip(winner_run: ContentRun, tmp_path: Path) -> None:
    rows = winner_rows(winner_run.result, winner_run.contents, records=winner_run.records)
    out = tmp_path / "winner.tsv"
    write_winner_tsv(rows, out)
    back = read_tsv(out, list(rows[0]))
    assert len(back) == len(rows) and back[0]["key"] == rows[0]["key"]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    name = "positive_identity_graduation.kdr_then_abl"
    inv_path, content = tmp_path / "inv.tsv", tmp_path / "content"
    get(name).build().to_tsv(inv_path)
    assert content_main(["sidecar", "--scenario", name, "--out-dir", str(content)]) == 0
    assert "ligands.tsv 54" in capsys.readouterr().out
    assert content_main(["detect", "--inventory", str(inv_path), "--content-dir", str(content)]) == 0
    out = capsys.readouterr().out
    assert "picked run_lig029" in out and "graduation" in out
    assert content_main(["detect", "--inventory", str(inv_path), "--content-dir", str(content), "--json"]) == 0
    assert '"graduation"' in capsys.readouterr().out
    winner = tmp_path / "w.tsv"
    assert content_main(["winner", "--inventory", str(inv_path), "--content-dir", str(content),
                         "--out", str(winner)]) == 0
    assert winner.read_text().splitlines()[0].startswith("key\troot\tcandidate_id\tlabel")
    capsys.readouterr()
    assert content_main(["manifest", "--inventory", str(inv_path)]) == 0
    assert f"{KDR}::run_lig029\tamber\tligand" in capsys.readouterr().out
    assert content_main(["manifest", "--inventory", str(inv_path), "--json"]) == 0
    assert '"desmond.trj_dir"' not in capsys.readouterr().out
    assert content_main(["sidecar", "--scenario", "positive_amber_basic.kdr_fep", "--out-dir",
                         str(tmp_path / "empty")]) == 0
    assert "declares no CONTENT" in capsys.readouterr().err
    assert content_main(["nope"]) == 2
    assert content_main(["--help"]) == 0
