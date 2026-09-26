"""Synthetic tree builder: determinism, copies, links and campaign layout."""

from __future__ import annotations

import io

from campaign_detector.synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy,
    pick_by_derived, pick_by_symlink,
)


def _tsv(tb: TreeBuilder) -> str:
    buf = io.StringIO()
    tb.build().to_tsv(buf)
    return buf.getvalue()


def _small_tree() -> TreeBuilder:
    tb = TreeBuilder("/vol1")
    names = md_campaign(tb, "proj/md", CampaignSpec(n_candidates=5, n_chunks=10, skip=frozenset({2})))
    d = human_analysis(tb, "proj", AnalysisSpec())
    pick_by_copy(tb, "/vol1/proj/md", d, names[:1], uid=3002, mtime=at(30, 10))
    pick_by_symlink(tb, d, "/vol1/proj/md", names[1:2], uid=3002, mtime=at(30, 11))
    pick_by_derived(tb, d, names[2:3], uid=3002, mtime=at(30, 12))
    return tb


def test_build_twice_is_identical() -> None:
    assert _tsv(_small_tree()) == _tsv(_small_tree())


def test_campaign_layout_and_pick_names() -> None:
    inv = _small_tree().build()
    assert [e.name for e in inv.children("/vol1/proj/md")] == ["run_lig001", "run_lig003", "run_lig004", "run_lig005"]
    names = {e.name for e in inv.children("/vol1/proj/md/run_lig001")}
    assert names == {"complex.prmtop", "prod.in", "prod.rst7", "slurm-4100000.out"} | {
        f"prod{k:03d}.{ext}" for k in range(1, 11) for ext in ("nc", "out")}
    a = "/vol1/proj/analysis"
    assert {"lig001_best.nc", "lig003_traj", "lig004_rmsd.png"} <= {e.name for e in inv.children(a)}
    assert inv.by_path[f"{a}/lig003_traj"].target == "../md/run_lig003/prod010.nc"
    assert inv.by_path[f"{a}/lig003_traj"].size == len("../md/run_lig003/prod010.nc")


def test_copy_shares_sha_and_boilerplate_is_shared() -> None:
    tb = TreeBuilder("/v")
    tb.file("a/x.nc", size=7, mtime=at(0, 1))
    tb.copy("a/x.nc", "b/y.nc", mtime=at(1, 1))
    small = tb.build()
    x, y = small.by_path["/v/a/x.nc"], small.by_path["/v/b/y.nc"]
    assert x.sha256 == y.sha256 and x.size == y.size and x.inode != y.inode
    inv = _small_tree().build()
    md = "/vol1/proj/md"
    assert inv.by_path[f"{md}/run_lig001/prod.in"].sha256 == inv.by_path[f"{md}/run_lig003/prod.in"].sha256
    assert inv.by_path[f"{md}/run_lig001/prod003.nc"].sha256 != inv.by_path[f"{md}/run_lig003/prod003.nc"].sha256
    assert inv.by_path["/vol1/proj/analysis/lig001_best.nc"].sha256 == inv.by_path[f"{md}/run_lig001/prod010.nc"].sha256


def test_hardlink_shares_inode_and_counts_links() -> None:
    tb = TreeBuilder("/v")
    tb.file("a/x.nc", size=7, mtime=at(0, 1))
    tb.hardlink("a/x.nc", "b/x.nc")
    inv = tb.build()
    a, b = inv.by_path["/v/a/x.nc"], inv.by_path["/v/b/x.nc"]
    assert a.inode == b.inode and a.nlink == b.nlink == 2 and a.sha256 == b.sha256


def test_inner_levels_and_dir_mtimes() -> None:
    tb = TreeBuilder("/v")
    md_campaign(tb, "fep", CampaignSpec(n_candidates=2, n_chunks=3, inner_fmt="lambda_{:.2f}", n_inner=3))
    inv = tb.build()
    assert [e.name for e in inv.children("/v/fep/run_lig001")] == ["lambda_0.00", "lambda_0.50", "lambda_1.00"]
    newest = max(e.mtime for e in inv.children("/v/fep/run_lig002/lambda_1.00"))
    assert inv.by_path["/v/fep/run_lig002/lambda_1.00"].mtime == newest


def test_expected_outcome_helpers() -> None:
    e = ExpectedOutcome.selection("/r/", ["a"], rest="not_picked")
    assert e.campaign_roots == {"/r"} and e.picked == {"/r": {"a"}} and e.rest == {"/r": "not_picked"}
    assert ExpectedOutcome.campaign_no_selection("/r").picked == {"/r": frozenset()}
    assert ExpectedOutcome.no_campaign().campaign_roots == frozenset()
