"""Detector mechanics on small hand-built trees."""

from __future__ import annotations

import json

import pytest

from campaign_detector.detect import Evidence, Hooks, Params, detect, is_tainted
from campaign_detector.synth import (
    AnalysisSpec, CampaignSpec, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy, pick_by_derived,
    pick_by_symlink,
)

ROOT = "/vol1/proj/md"
A = "/vol1/proj/md/analysis"
LATER = at(30, 11)


def _tree(n: int = 12) -> tuple[TreeBuilder, list[str]]:
    tb = TreeBuilder("/vol1")
    names = md_campaign(tb, ROOT, CampaignSpec(n_candidates=n, n_chunks=10))
    human_analysis(tb, ROOT, AnalysisSpec())
    return tb, names


def test_is_tainted() -> None:
    assert is_tainted("/vol1/a/old/x.nc") and is_tainted("/vol1/a/lig1_BackUp") and is_tainted("/tmp_runs/x")
    assert not is_tainted("/vol1/templates/final") and not is_tainted("/vol1/proj/md/analysis")


def test_no_selection_means_all_unknown() -> None:
    tb, _ = _tree()
    (rep,) = detect(tb.build()).campaigns
    assert rep.unknown() == {c.id for c in rep.candidates} and rep.selection_confidence == 0.0


def test_mirror_is_not_a_campaign_and_is_capped() -> None:
    tb, names = _tree()
    for n in names:
        for f in ("prod001.nc", "prod002.nc", "prod.in", "complex.prmtop"):
            tb.copy(f"{ROOT}/{n}/{f}", f"/vol2/mirror/{n}/{f}", uid=3002, mtime=at(30, 10))
    pick_by_copy(tb, ROOT, A, names[3:4], uid=3002, mtime=LATER)
    result = detect(tb.build())
    assert result.campaign_roots == [ROOT]
    (rep,) = result.campaigns
    assert rep.picked() == {names[3]}
    assert any("ignored /vol2/mirror" in n for n in rep.notes)


def test_coverage_cap_drops_symlink_index_but_keeps_real_pick() -> None:
    tb, names = _tree()
    index = f"{A}/index"
    pick_by_symlink(tb, index, ROOT, names, uid=3002, mtime=LATER)
    for f in ("README.md", "notes.txt"):
        tb.file(f"{index}/{f}", size=100, mtime=LATER, uid=3002)
    pick_by_derived(tb, A, names[5:6], uid=3002, mtime=LATER)
    (rep,) = detect(tb.build()).campaigns
    assert f"{A}/index" in [c.path for c in rep.curated_dirs]
    assert rep.picked() == {names[5]}
    assert any(n.startswith(f"dropped 12 symlink links from {index}") for n in rep.notes)


def test_tainted_and_boilerplate_copies_do_not_count() -> None:
    tb, names = _tree()
    pick_by_copy(tb, ROOT, f"{A}/old", names[:1], uid=3002, mtime=LATER)
    tb.copy(f"{ROOT}/{names[1]}/prod.in", f"{A}/prod.in", mtime=LATER, uid=3002)
    (rep,) = detect(tb.build()).campaigns
    assert not rep.picked() and all(not c.evidence for c in rep.candidates)


def test_hardlink_evidence() -> None:
    tb, names = _tree()
    tb.hardlink(f"{ROOT}/{names[2]}/prod010.nc", f"{A}/keep.nc")
    (rep,) = detect(tb.build()).campaigns
    (cand,) = [c for c in rep.candidates if c.label == "picked"]
    assert cand.id == names[2] and [e.kind for e in cand.evidence] == ["hardlink"]


def test_broad_selection_reverts_to_unknown() -> None:
    tb, names = _tree(24)
    pick_by_copy(tb, ROOT, A, names[:18], uid=3002, mtime=LATER)
    # One call copies 18 of 24 at a 60 s cadence in id order: machine-shaped, so the ambiguous-band rule
    # drops it first. Switch that rule off to exercise the selection-confidence backstop on its own.
    (rep,) = detect(tb.build(), params=Params(machine_band=1.0)).campaigns
    assert not rep.picked() and rep.unknown() == set(names)
    assert rep.selection_confidence == pytest.approx(0.25)
    assert any("selection confidence" in n for n in rep.notes)
    (default,) = detect(tb.build()).campaigns
    assert not default.picked() and any("machine-shaped" in n for n in default.notes)


def test_hooks_add_evidence_and_are_validated() -> None:
    tb, names = _tree()

    def mentions(inv, report):
        return [Evidence("text_mention", names[7], f"{A}/notes.txt", report.candidates[7].path, 0.8)]

    (rep,) = detect(tb.build(), hooks=Hooks(text_mentions=mentions)).campaigns
    assert rep.picked() == {names[7]}

    def bogus(inv, report):
        return [Evidence("graduation", "nope", "/x", "/y", 1.0)]

    with pytest.raises(ValueError):
        detect(tb.build(), hooks=Hooks(graduation=bogus))


def test_graduation_is_weak_and_min_candidates_gate() -> None:
    tb, names = _tree()
    tb.dir("/vol1/leads/lig004_resynthesis", mtime=LATER)
    (rep,) = detect(tb.build()).campaigns
    (cand,) = [c for c in rep.candidates if c.evidence]
    assert cand.id == "run_lig004" and cand.label == "unknown" and cand.evidence[0].kind == "graduation"
    assert detect(tb.build(), params=Params(min_candidates=13)).campaigns == []


def test_to_dict_is_json_serialisable() -> None:
    tb, names = _tree()
    pick_by_copy(tb, ROOT, A, names[:1], uid=3002, mtime=LATER)
    data = json.loads(json.dumps(detect(tb.build()).to_dict()))
    assert data["campaigns"][0]["candidates"][0]["label"] == "picked"


def test_taint_is_relative_to_the_campaign() -> None:
    assert not is_tainted("/scratch/u/fep/analysis", anchor="/scratch/u/fep")
    assert is_tainted("/scratch/u/fep/analysis/old", anchor="/scratch/u/fep")
    tb = TreeBuilder("/scratch")
    names = md_campaign(tb, "/scratch/u/fep", CampaignSpec(n_candidates=8, n_chunks=10))
    a = human_analysis(tb, "/scratch/u/fep", AnalysisSpec())
    pick_by_copy(tb, "/scratch/u/fep", a, names[2:3], uid=3002, mtime=LATER)
    (rep,) = detect(tb.build()).campaigns
    assert rep.picked() == {names[2]}


def test_symlink_only_folder_is_curated() -> None:
    tb, names = _tree()
    pick_by_symlink(tb, "/vol1/proj/final_picks", ROOT, names[2:4], uid=3002, mtime=LATER)
    (rep,) = detect(tb.build()).campaigns
    assert "/vol1/proj/final_picks" in [c.path for c in rep.curated_dirs]
    assert rep.picked() == set(names[2:4])


def test_sibling_batches_stay_separate_campaigns() -> None:
    tb = TreeBuilder("/vol3")
    for b in range(1, 5):
        md_campaign(tb, f"p/batch{b}", CampaignSpec(n_candidates=6, n_chunks=4, start=at(7 * b, 3)))
    assert detect(tb.build()).campaign_roots == [f"/vol3/p/batch{b}" for b in range(1, 5)]


def test_replica_levels_fold_into_candidates() -> None:
    tb = TreeBuilder("/vol2")
    md_campaign(tb, "abfe", CampaignSpec(engine="gromacs", n_candidates=6, candidate_fmt="cmpd{:02d}",
                                         inner_fmt="lambda_{:.2f}", n_inner=12, n_chunks=4, boilerplate=("md.mdp",)))
    human_analysis(tb, "/vol2", AnalysisSpec())
    pick_by_copy(tb, "/vol2/abfe", "/vol2/analysis", ["cmpd03"], src_name="lambda_0.00/traj004.xtc",
                 rename="{id}_final.xtc", uid=3002, mtime=LATER)
    (rep,) = detect(tb.build()).campaigns
    assert rep.root == "/vol2/abfe" and rep.engine == "gromacs" and rep.n_candidates == 6
    assert rep.picked() == {"cmpd03"}


def test_hook_evidence_must_use_absolute_paths() -> None:
    tb, names = _tree()

    def relative(inv, report):
        return [Evidence("text_mention", names[0], "notes.txt", "x", 1.0)]

    with pytest.raises(ValueError):
        detect(tb.build(), hooks=Hooks(text_mentions=relative))
