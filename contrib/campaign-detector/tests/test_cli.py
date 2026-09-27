"""Command line entry points, run in-process."""

from __future__ import annotations

import json

from campaign_detector.cli import SUBCOMMANDS, main


def test_demo_passes(capsys) -> None:
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "positive_amber_basic.kdr_fep" in out
    assert " 0 FAIL" in out and " 0 XPASS" in out


def test_synth_detect_round_trip(tmp_path, capsys) -> None:
    tsv = tmp_path / "kdr.tsv"
    assert main(["synth", "--scenario", "positive_amber_basic.kdr_fep", "--out", str(tsv)]) == 0
    assert main(["detect", "--inventory", str(tsv), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    (camp,) = data["campaigns"]
    assert camp["root"] == "/vol3/projects/KDR_2011/fep"
    assert sorted(c["id"] for c in camp["candidates"] if c["label"] == "picked") == [
        "run_lig012", "run_lig029", "run_lig041"]
    assert main(["detect", "--inventory", str(tsv)]) == 0
    assert "picked run_lig041" in capsys.readouterr().out


def test_features_and_list(tmp_path, capsys) -> None:
    tsv, feats = tmp_path / "kdr.tsv", tmp_path / "feats.tsv"
    main(["synth", "--scenario", "positive_amber_basic.kdr_fep", "--out", str(tsv)])
    assert main(["features", "--inventory", str(tsv), "--out", str(feats)]) == 0
    header, *rows = feats.read_text().splitlines()
    assert "traj_chunk_regularity" in header.split("\t") and "signature" not in header.split("\t")
    assert len(rows) == sum(1 for line in tsv.read_text().splitlines() if "\td\t" in line)
    assert main(["synth", "--list"]) == 0
    assert "positive_amber_basic.kdr_fep" in capsys.readouterr().out


def test_dispatch() -> None:
    assert set(SUBCOMMANDS) >= {"synth", "detect", "features", "demo"}
    assert main([]) == 2 and main(["nope"]) == 2


def test_usage_aligns_every_subcommand(capsys) -> None:
    assert main(["--help"]) == 0
    rows = [line for line in capsys.readouterr().err.splitlines() if line.startswith("  ")]
    starts = {line.index("``") for line in rows}
    assert len(rows) == len(SUBCOMMANDS) and len(starts) == 1  # descriptions share one column
