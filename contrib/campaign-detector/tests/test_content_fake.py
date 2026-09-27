"""Sidecar TSVs, the FakeReader and per-candidate aggregation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from campaign_detector.content import sidecar
from campaign_detector.content.aggregate import aggregate
from campaign_detector.content.fake import FakeReader, fake_registry
from campaign_detector.content.manifest import candidate_records
from campaign_detector.content.model import FileRef, LigandIdentity, ReaderResult
from campaign_detector.content.sidecar import SidecarBuilder, fake_inchikey
from campaign_detector.detect import detect
from campaign_detector.scenarios import get
from campaign_detector.scenarios.positive_identity_graduation import KDR_ROOT, kdr_compound, kdr_smiles

BASE = "positive_identity_graduation.kdr_then_abl"
LIG029_MOL2 = f"{KDR_ROOT}/run_lig029/lig029.mol2"
KEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")


@pytest.fixture(scope="module")
def base_content(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("sidecar")
    sidecar.write(get(BASE), out)
    return out


def test_fake_inchikey_is_valid_deterministic_and_stereo_aware() -> None:
    k = fake_inchikey("C[C@H](N)O")
    assert KEY_RE.match(k) and k.endswith("SA-N")
    assert k == fake_inchikey("C[C@H](N)O")
    other = fake_inchikey("C[C@@H](N)O")
    flat = fake_inchikey("C[CH](N)O")
    assert k != other and k[:14] == other[:14] == flat[:14]
    assert fake_inchikey("CCO")[:14] != fake_inchikey("CCN")[:14]
    assert fake_inchikey("CCO")[15:23] != fake_inchikey("CCO")[:8]


def test_sidecar_builder_validates() -> None:
    sb = SidecarBuilder()
    with pytest.raises(ValueError):
        sb.ligand("/a/b.sdf", "CCO", role="solvent")
    with pytest.raises(ValueError):
        sb.ligand("/a/b.sdf", "CCO", confidence="certain")
    with pytest.raises(ValueError):
        sb.mention("/a/n.txt", "lig1", kind="rumour")
    with pytest.raises(ValueError):
        sb.metric("/a/x.out", "t", 1.0, cost="huge")
    with pytest.raises(ValueError):
        sb.ligand("relative/b.sdf", "CCO")
    row = sb.ligand("/a/b.sdf", "C[C@H](N)O")
    assert row.stereo == "specified" and row.inchikey == fake_inchikey("C[C@H](N)O")


def test_scenario_sidecars_are_tsv_sorted_and_deterministic(base_content: Path, tmp_path: Path) -> None:
    assert sorted(p.name for p in base_content.iterdir()) == ["ligands.tsv", "mentions.tsv", "metrics.tsv"]
    lines = (base_content / "ligands.tsv").read_text().splitlines()
    assert lines[0].split("\t") == list(sidecar.LIGAND_COLUMNS)
    assert len(lines) == 1 + 46 + 8
    assert lines[1:] == sorted(lines[1:])
    again = tmp_path / "again"
    counts = sidecar.write(get(BASE), again)
    assert counts == {"ligands.tsv": 54, "metrics.tsv": 46 * 5, "mentions.tsv": 0}
    for name in sidecar.SIDECAR_FILES:
        assert (again / name).read_bytes() == (base_content / name).read_bytes()


def test_sidecar_round_trip_matches_inventory_hashes(base_content: Path) -> None:
    inv = get(BASE).build()
    data = sidecar.read(base_content)
    assert len(data.ligands) == 54 and len(data.metrics) == 230 and not data.mentions
    for row in data.ligands + data.metrics:
        assert row["sha256"] == inv.by_path[row["path"] or ""].sha256
    row = next(r for r in data.ligands if r["path"] == LIG029_MOL2)
    assert row["name"] == "KDR-0877" and row["inchikey"] == fake_inchikey(kdr_smiles(29))
    assert row["inchikey14"] == (row["inchikey"] or "")[:14]


def test_scenario_without_content_writes_empty_sidecars(tmp_path: Path) -> None:
    counts = sidecar.write(get("positive_amber_basic.kdr_fep"), tmp_path)
    assert counts == {"ligands.tsv": 0, "metrics.tsv": 0, "mentions.tsv": 0}
    assert (tmp_path / "ligands.tsv").read_text() == "\t".join(sidecar.LIGAND_COLUMNS) + "\n"
    assert len(sidecar.read(tmp_path)) == 0
    assert len(sidecar.read(tmp_path / "missing")) == 0


def test_sidecar_paths_must_exist_in_the_inventory(tmp_path: Path) -> None:
    sb = SidecarBuilder()
    sb.ligand("/nowhere/x.sdf", "CCO")
    with pytest.raises(ValueError, match="not in the inventory"):
        sidecar.write(sb, tmp_path, inv=get("positive_amber_basic.kdr_fep").build())
    assert sidecar.write(sb, tmp_path)["ligands.tsv"] == 1  # no inventory: sha cells empty
    assert sidecar.read(tmp_path).ligands[0]["sha256"] is None


def _ref(inv_path: str, sha: str | None) -> FileRef:
    return FileRef(inv_path, sha, 6000, 0, "STRUCT", "mol2")


def test_fake_reader_serves_declared_facts(base_content: Path) -> None:
    inv = get(BASE).build()
    reader = FakeReader(base_content)
    sha = inv.by_path[LIG029_MOL2].sha256
    ref = _ref(LIG029_MOL2, sha)
    assert reader.can_read(ref)
    res = reader.read(ref)
    assert res.reader == "fake-sidecar" and res.toolkit == "sidecar" and res.input_sha256 == sha
    (lig,) = res.ligands
    assert (lig.name, lig.inchikey, lig.confidence, lig.role) == (
        "KDR-0877", fake_inchikey(kdr_smiles(29)), "high", "ligand")
    assert lig.source_path == LIG029_MOL2 and lig.inchikey14 == fake_inchikey(kdr_smiles(29))[:14]
    assert res == FakeReader(base_content).read(ref), "reads must be deterministic"
    # a byte copy elsewhere carries the same facts, with its own provenance
    copy = reader.read(_ref("/vol9/share/lig029_copy.mol2", sha))
    assert copy.ligands[0].source_path == "/vol9/share/lig029_copy.mol2"
    # a stale sidecar (hash mismatch) or an undeclared file is refused
    assert not reader.can_read(_ref(LIG029_MOL2, "0" * 64))
    assert not reader.can_read(_ref("/vol9/other.mol2", None))
    with pytest.raises(KeyError):
        reader.read(_ref("/vol9/other.mol2", None))


def test_fake_reader_results_aggregate_per_candidate(base_content: Path) -> None:
    inv = get(BASE).build()
    records = {r.candidate_id: r for r in candidate_records(inv, detect(inv))}
    reg = fake_registry(base_content)
    rec = records["run_lig029"]
    results = reg.read_candidate(rec)
    assert sorted(r.input_path.rsplit("/", 1)[1] for r in results) == ["lig029.mol2", "prod020.out",
                                                                       "ti_summary.csv"]
    content = aggregate(rec, results)
    assert content.key == f"{KDR_ROOT}::run_lig029"
    assert content.best is not None and content.best.name == kdr_compound(29)
    assert content.metrics["sim_time_ns"] == 50.0 and "exp_dg" in content.metrics
    assert content.metric_sources["dg_pred"] == (f"{KDR_ROOT}/run_lig029/ti_summary.csv",)
    assert content.flags == set() and content.n_results == 3
    abl = aggregate(records["cpd03"], reg.read_candidate(records["cpd03"]))
    assert abl.best is not None and abl.best.inchikey == content.best.inchikey
    # results for files outside the candidate are ignored
    assert aggregate(rec, reg.read_candidate(records["cpd03"])).best is None


def _lig(key: str, path: str, conf: str = "high", role: str = "ligand") -> LigandIdentity:
    return LigandIdentity(role, None, key, key[:14], None, None, "c", "none", conf, path, "1")


def test_aggregate_best_identity_flags_and_metric_means(base_content: Path) -> None:
    inv = get(BASE).build()
    rec = next(r for r in candidate_records(inv, detect(inv)) if r.candidate_id == "run_lig001")
    p = rec.path
    k1, k2 = "A" * 14 + "-BBBBBBBBSA-N", "C" * 14 + "-DDDDDDDDSA-N"
    res = ReaderResult("r", "1", "t", "1", f"{p}/lig001.mol2", None, "small",
                       ligands=[_lig(k1, f"{p}/lig001.mol2", "medium"), _lig(k2, f"{p}/lig001.mol2", "high"),
                                _lig("E" * 14 + "-FFFFFFFFSA-N", f"{p}/lig001.mol2", "high", role="cofactor")],
                       flags=["bond_orders_perceived"])
    res2 = ReaderResult("r", "1", "t", "1", f"{p}/complex.prmtop", None, "small",
                        ligands=[_lig(k1, f"{p}/complex.prmtop", "medium")])
    content = aggregate(rec, [res, res2])
    assert content.best is not None and content.best.inchikey == k2, "confidence beats support"
    assert {"multiple_ligands", "bond_orders_perceived"} <= content.flags
    assert "identity_agree" not in content.flags
    assert [i.inchikey for i in content.identities()] == [k1, k2]
    only_k1 = aggregate(rec, [res2, ReaderResult("r", "1", "t", "1", f"{p}/lig001.mol2", None, "small",
                                                 ligands=[_lig(k1, f"{p}/lig001.mol2", "medium")])])
    assert "identity_agree" in only_k1.flags
    assert "no_identity" in aggregate(rec, []).flags
