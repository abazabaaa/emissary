"""End-to-end smoke test on the grounded KDR FEP scenario."""

from __future__ import annotations

from campaign_detector.cli import main
from campaign_detector.detect import detect
from campaign_detector.scenarios import get
from campaign_detector.synth import compare

ROOT = "/vol3/projects/KDR_2011/fep"


def test_kdr_fep_end_to_end() -> None:
    s = get("positive_amber_basic.kdr_fep")
    result = detect(s.build())
    assert result.campaign_roots == [ROOT]
    (rep,) = result.campaigns
    assert rep.engine == "amber" and rep.era == 2011 and rep.template == "run_lig#"
    assert rep.n_candidates == 46
    assert rep.missing_ids == ["run_lig017", "run_lig033"]
    assert rep.submitter_uid == 2001 and rep.confidence > 0.9
    assert [c.path for c in rep.curated_dirs] == [f"{ROOT}/analysis"]
    assert rep.picked() == {"run_lig012", "run_lig029", "run_lig041"}
    assert len(rep.not_picked()) == 43 and not rep.unknown()
    kinds = {c.id: {e.kind for e in c.evidence} for c in rep.candidates if c.evidence}
    assert kinds == {"run_lig012": {"copy_out"}, "run_lig029": {"derived"}, "run_lig041": {"symlink"}}
    assert compare(s.expected, result) == []


def test_old_copy_is_not_a_pick() -> None:
    rep = detect(get("positive_amber_basic.kdr_fep").build()).campaigns[0]
    lig005 = next(c for c in rep.candidates if c.id == "run_lig005")
    assert lig005.label == "not_picked" and not lig005.evidence


def test_demo_exit_code() -> None:
    assert main(["demo"]) == 0
