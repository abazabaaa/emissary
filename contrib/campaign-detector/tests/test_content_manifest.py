"""Content model, manifest (file classes, candidate records), registry dispatch and result cache."""

from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

import pytest

from campaign_detector.content import model
from campaign_detector.content.cache import ResultCache, rebind, ref_key
from campaign_detector.content.manifest import (
    candidate_records, candidate_unit, classify_content, classify_content_name, record_files,
)
from campaign_detector.content.model import (
    CandidateRecord, FileRef, LigandIdentity, Mention, Metric, Reader, ReaderResult, read_tsv, write_tsv,
)
from campaign_detector.content.registry import ANY_FORMAT, ReaderRegistry, StubReader, stub_registry
from campaign_detector.detect import detect
from campaign_detector.scenarios import get
from campaign_detector.synth import T0, TreeBuilder

# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------


def test_model_imports_only_the_standard_library() -> None:
    tree = ast.parse(Path(model.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "model.py must not import from the package"
            assert node.module and node.module.split(".")[0] in sys.stdlib_module_names | {"__future__"}
        elif isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] in sys.stdlib_module_names for a in node.names)


def test_candidate_record_key_and_ranks() -> None:
    rec = CandidateRecord("/v/root", "run_lig001", "/v/root/run_lig001", "amber", 2011, 1, 2, "picked", "ligand",
                          (), {"TOPO": (FileRef("/v/root/run_lig001/b.prmtop", None, 1, 1, "TOPO", "amber.prmtop"),),
                               "INPUT": (FileRef("/v/root/run_lig001/a.in", None, 1, 1, "INPUT", "amber.mdin"),)})
    assert rec.key == "/v/root::run_lig001"
    assert [r.path for r in rec.all_files()] == ["/v/root/run_lig001/a.in", "/v/root/run_lig001/b.prmtop"]
    assert model.cost_rank("header") < model.cost_rank("small") < model.cost_rank("large")
    assert model.confidence_rank("high") > model.confidence_rank("medium") > model.confidence_rank("low") \
        > model.confidence_rank(None)
    assert model.connectivity_block("ABCDEFGHIJKLMN-OPQRSTUVSA-N") == "ABCDEFGHIJKLMN"
    assert model.connectivity_block(None) is None


def test_tsv_cells_round_trip_escapes() -> None:
    rows = [("a\tb", None, 1.5, "line\nbreak\\x\r"), ("plain", "", 0.1, "x")]
    buf = io.StringIO()
    write_tsv(buf, ("c1", "c2", "c3", "c4"), rows)
    assert buf.getvalue().count("\n") == 3
    buf.seek(0)
    back = read_tsv(buf, ("c1", "c2", "c3", "c4"))
    assert back[0] == {"c1": "a\tb", "c2": None, "c3": "1.5", "c4": "line\nbreak\\x\r"}
    assert back[1]["c2"] is None and float(back[1]["c3"] or 0) == 0.1
    with pytest.raises(ValueError):
        read_tsv(io.StringIO("wrong\theader\n"), ("c1", "c2"))
    with pytest.raises(ValueError):
        write_tsv(io.StringIO(), ("a", "b"), [("only one",)])


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name, parent, engine, expected", [
    ("lig.oeb.gz", "", None, ("STRUCT", "oeb")),
    ("confs.OEB.GZ", "", None, ("STRUCT", "oeb")),
    ("lig.sdf.gz", "", None, ("STRUCT", "sdf")),
    ("x.oez", "", None, ("STRUCT", "oez")),
    ("receptor.oedu", "", None, ("STRUCT", "oedu")),
    ("ligands.maegz", "", None, ("STRUCT", "mae")),
    ("dock_pv.maegz", "", None, ("STRUCT", "glide.pv")),
    ("dock_pv.mae.gz", "", None, ("STRUCT", "glide.pv")),
    ("dock_lib.maegz", "", None, ("STRUCT", "glide.lib")),
    ("md-out.cms", "", None, ("TOPO", "desmond.cms")),
    ("md-out.cfg", "", None, ("INPUT", "desmond.cfg")),
    ("kdr_out.fmp", "", None, ("RESULT", "fep.fmp")),
    ("kdr.fmp", "", None, ("RESULT", "fep.fmp")),
    ("multisim.log", "", "desmond", ("LOG", "desmond.multisim_log")),
    ("md.ene", "", None, ("LOG", "desmond.ene")),
    ("frame000000001", "md_trj", None, ("TRAJ", "desmond.trj_frame")),
    ("clickme.dtr", "md_trj", None, ("TRAJ", "desmond.trj_frame")),
    ("complex.prmtop", "", "amber", ("TOPO", "amber.prmtop")),
    ("prod007.out", "", "amber", ("LOG", "amber.mdout")),
    ("prod.in", "", "amber", ("INPUT", "amber.mdin")),
    ("prod001.nc", "", "amber", ("TRAJ", "amber.nc")),
    ("md.log", "", "gromacs", ("LOG", "gromacs.log")),
    ("traj001.dcd", "", "namd", ("TRAJ", "namd.dcd")),
    ("traj001.dcd", "", None, ("TRAJ", "dcd")),
    ("slurm-4100001.out", "", "amber", ("SCHED", "sched.slurm")),
    ("job.o4100001", "", "desmond", ("SCHED", "sched.pbs")),
    ("rmsd_lig.dat", "", None, ("RESULT", "analysis.series")),
    ("results.csv", "", None, ("RESULT", "csv")),
    ("md.rst", "", "amber", ("RESTART", "amber.rst7")),
    ("README.rst", "", None, ("DERIVED", "text")),
    ("notes.txt", "", None, ("DERIVED", "text")),
    ("weird.bin", "", None, ("OTHER", "bin")),
    ("README", "", None, ("OTHER", "unknown")),
])
def test_classify_content_name(name: str, parent: str, engine: str | None, expected: tuple[str, str]) -> None:
    assert classify_content_name(name, parent_name=parent, engine=engine) == expected


def test_classify_content_dirs() -> None:
    assert classify_content_name("md_trj", is_dir=True) == ("TRAJ", "desmond.trj_dir")
    assert classify_content_name("rep1", is_dir=True) == ("OTHER", "dir")


@pytest.mark.parametrize("cid, unit", [
    ("run_lig012", "ligand"), ("cpd03", "ligand"), ("lig01_lig07", "edge"), ("lig1_to_lig2", "edge"),
    ("complex_leg", "leg"), ("solvent", "leg"), ("setup", "unknown"), ("cpd12_v2", "ligand"),
    ("lig05_rep1", "ligand"), ("kdr2_lig05", "ligand"), ("cpd3_cpd9", "edge"),
])
def test_candidate_unit(cid: str, unit: str) -> None:
    assert candidate_unit(cid) == unit


def test_candidate_records_on_kdr_fep() -> None:
    inv = get("positive_amber_basic.kdr_fep").build()
    result = detect(inv)
    records = candidate_records(inv, result)
    assert len(records) == 46
    assert [r.key for r in records] == sorted(r.key for r in records)
    assert len({r.key for r in records}) == 46
    labels = {c.id: c.label for c in result.campaigns[0].candidates}
    for rec in records:
        assert rec.root == "/vol3/projects/KDR_2011/fep" and rec.engine == "amber" and rec.era == 2011
        assert rec.unit == "ligand" and rec.replicas == () and rec.label == labels[rec.candidate_id]
        fmts = {cls: {f.fmt for f in refs} for cls, refs in rec.files.items()}
        assert fmts == {"TOPO": {"amber.prmtop"}, "INPUT": {"amber.mdin"}, "TRAJ": {"amber.nc"},
                        "RESTART": {"amber.rst7"}, "LOG": {"amber.mdout"}, "SCHED": {"sched.slurm"}}
        trajs = rec.files["TRAJ"]
        assert len(trajs) == 20 and len(rec.files["LOG"]) == 20
        assert all(t.companions == (f"{rec.path}/complex.prmtop",) for t in trajs)
        assert all(f.sha256 for f in rec.all_files())


def _desmond_fep_tree() -> TreeBuilder:
    """One FEP+-like edge directory: lambda/replica levels with Desmond ``_trj`` dirs inside."""
    tb = TreeBuilder(root="/vol8")
    edge = "/vol8/fep/lig01_lig07"
    for lam in ("lambda_0.00", "lambda_1.00"):
        for rep in ("rep1", "rep2"):
            d = f"{edge}/{lam}/{rep}"
            tb.file(f"{d}/md-out.cms", size=5_000_000, mtime=T0 + 100)
            tb.file(f"{d}/md-out.cfg", size=4_000, mtime=T0 + 100)
            tb.file(f"{d}/md.ene", size=40_000, mtime=T0 + 900)
            for k in range(3):
                tb.file(f"{d}/md_trj/frame00000000{k}", size=1_000_000, mtime=T0 + 200 + k)
            tb.file(f"{d}/md_trj/clickme.dtr", size=100, mtime=T0 + 150)
    tb.file(f"{edge}/kdr_out.fmp", size=3_000_000, mtime=T0 + 1000)
    tb.file(f"{edge}/ligands_pv.maegz", size=900_000, mtime=T0 + 50)
    return tb


def test_record_files_fold_desmond_trj_dirs_at_any_depth() -> None:
    inv = _desmond_fep_tree().build()
    files, replicas = record_files(inv, "/vol8/fep/lig01_lig07", engine="desmond")
    assert replicas == ("lambda_0.00", "lambda_0.00/rep1", "lambda_0.00/rep2", "lambda_1.00",
                        "lambda_1.00/rep1", "lambda_1.00/rep2")
    trajs = files["TRAJ"]
    assert [t.fmt for t in trajs] == ["desmond.trj_dir"] * 4
    first = trajs[0]
    assert first.path == "/vol8/fep/lig01_lig07/lambda_0.00/rep1/md_trj"
    assert first.size == 3_000_100 and first.mtime == T0 + 202 and first.sha256 is None
    assert first.companions == ("/vol8/fep/lig01_lig07/lambda_0.00/rep1/md-out.cms",)
    every = [f.path for refs in files.values() for f in refs]
    assert not any("/md_trj/" in p for p in every), "frame files must fold into their _trj dir"
    assert {f.fmt for f in files["RESULT"]} == {"fep.fmp"}
    assert {f.fmt for f in files["STRUCT"]} == {"glide.pv"}
    assert classify_content(inv.by_path["/vol8/fep/lig01_lig07/lambda_0.00/rep1/md_trj"]) == \
        ("TRAJ", "desmond.trj_dir")


# --------------------------------------------------------------------------
# registry and cache
# --------------------------------------------------------------------------


def _ref(path: str, fmt: str, sha: str | None = "s1") -> FileRef:
    return FileRef(path, sha, 10, T0, "STRUCT", fmt)


class _Boom:
    name, version, cost = "boom", "1", "small"

    def can_read(self, ref: FileRef) -> bool:
        return True

    def read(self, ref: FileRef) -> ReaderResult:
        raise RuntimeError("license server unreachable")


def test_registry_dispatch_by_engine_format_priority_and_cost() -> None:
    reg = ReaderRegistry()
    oe = StubReader("oe", ["sdf"], toolkit="openeye")
    sd = StubReader("sdgr", ["sdf", "mae"], toolkit="schrodinger")
    amber_only = StubReader("amber-only", ["sdf"], toolkit="oss")
    big = StubReader("traj", ["sdf"], toolkit="oss", cost="large")
    anyfmt = StubReader("any", [], toolkit="oss")
    anyfmt.can_read = lambda ref: ref.path.endswith(".sdf")  # type: ignore[method-assign]
    assert isinstance(oe, Reader)
    reg.register(oe, fmts=["sdf"])
    reg.register(sd, fmts=["sdf", "mae"], priority=5)
    reg.register(amber_only, fmts=["sdf"], engines=["amber"])
    reg.register(big, fmts=["sdf"])
    reg.register(anyfmt, fmts=[ANY_FORMAT])
    ref = _ref("/x/lig.sdf", "sdf")
    assert [r.name for r in reg.for_file(ref, "amber")] == ["sdgr", "oe", "amber-only", "traj", "any"]
    assert [r.name for r in reg.for_file(ref, "gromacs")] == ["sdgr", "oe", "traj", "any"]
    assert [r.name for r in reg.for_file(ref, None)] == ["sdgr", "oe", "traj", "any"]
    assert [r.name for r in reg.for_file(_ref("/x/a.mae", "mae"), "amber")] == ["sdgr"]
    got = reg.read_file(ref, "amber", max_cost="small")
    assert [r.reader for r in got] == ["sdgr", "oe", "amber-only", "any"]
    assert [r.reader for r in reg.read_file(ref, "amber", max_cost="large")][-2:] == ["traj", "any"]
    assert [r.name for r in reg.readers()] == ["oe", "sdgr", "amber-only", "traj", "any"]
    with pytest.raises(TypeError):
        reg.register(object(), fmts=["sdf"])  # type: ignore[arg-type]


def test_registry_cache_reads_each_content_once_and_rebinds_paths() -> None:
    class Ident(StubReader):
        def read(self, ref: FileRef) -> ReaderResult:
            res = super().read(ref)
            res.ligands.append(LigandIdentity("ligand", None, "K", "K", None, None, "c", "none", "high", ref.path, "1"))
            return res

    reader = Ident("ident", ["sdf"], toolkit="t")
    reg = ReaderRegistry()
    reg.register(reader, fmts=["sdf"])
    cache = ResultCache()
    a = reg.read_file(_ref("/x/a.sdf", "sdf", "same"), None, cache=cache)
    b = reg.read_file(_ref("/y/copy.sdf", "sdf", "same"), None, cache=cache)
    assert reader.calls == 1 and cache.hits == 1 and cache.misses == 1 and len(cache) == 1
    assert a[0].input_path == "/x/a.sdf" and a[0].ligands[0].source_path == "/x/a.sdf"
    assert b[0].input_path == "/y/copy.sdf" and b[0].ligands[0].source_path == "/y/copy.sdf"
    reg.read_file(_ref("/z/nohash.sdf", "sdf", None), None, cache=cache)
    reg.read_file(_ref("/z/nohash.sdf", "sdf", None), None, cache=cache)
    assert reader.calls == 2, "sha-less files are cached by path|size|mtime"
    with pytest.raises(ValueError, match="no sha256"):
        cache.put(ReaderResult("r", "1", "t", "1", "/z/nohash.sdf", None, "small"))
    assert ref_key(_ref("/z/nohash.sdf", "sdf", None)) == f"meta:/z/nohash.sdf|10|{T0}"


def test_registry_records_errors_without_caching_them() -> None:
    reg = ReaderRegistry()
    reg.register(_Boom(), fmts=["sdf"])
    cache = ResultCache()
    res = reg.read_file(_ref("/x/a.sdf", "sdf"), None, cache=cache)
    assert res[0].errors == ["RuntimeError: license server unreachable"] and len(cache) == 0


def test_stub_registry_routes_kdr_candidate() -> None:
    inv = get("positive_amber_basic.kdr_fep").build()
    rec = candidate_records(inv, detect(inv))[0]
    results = stub_registry().read_candidate(rec)
    readers = {(r.reader, rec_fmt) for r in results for rec_fmt in
               {f.fmt for f in rec.all_files() if f.path == r.input_path}}
    assert ("oss-reader", "amber.prmtop") in readers and ("oss-reader", "amber.mdout") in readers
    assert all(r.flags == ["stub"] for r in results)
    assert not any(r.input_path.endswith(".nc") for r in results)


def test_result_cache_tsv_round_trip(tmp_path: Path) -> None:
    res = ReaderResult(
        reader="r", reader_version="2", toolkit="tk", toolkit_version="1.0", input_path="/a/b.sdf",
        input_sha256="abc", cost="small", license_feature=None,
        ligands=[LigandIdentity("ligand", "KDR-0877", "AAAAAAAAAAAAAA-BBBBBBBBSA-N", "AAAAAAAAAAAAAA", "C\tC", None,
                                "canon", "none", "high", "/a/b.sdf", "1")],
        metrics=[Metric("dg_pred", -9.25, "kcal/mol", "/a/b.sdf", "small", "node")],
        mentions=[Mention("lig029", "candidate_id", "/a/b.sdf")],
        flags=["bond_orders_perceived"], errors=["warn;\nsecond line"], elapsed_s=0.5,
    )
    cache = ResultCache()
    cache.put(res)
    cache.put(rebind(res, "/c/d.sdf"), key="meta:/c/d.sdf|1|2")
    cache.save(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        ["cache_results.tsv", "cache_ligands.tsv", "cache_metrics.tsv", "cache_mentions.tsv", "cache_notes.tsv"])
    back = ResultCache.load(tmp_path)
    assert back.items() == cache.items()
