"""Featurizer: name analysis, the integer time model and directory features."""

from __future__ import annotations

import pytest

from campaign_detector.features import (
    T0, all_features, at, classify_name, era, has_version_marker, id_token, id_tokens, is_templated,
    is_working_hours, local_hour, sibling_uniformity, template_key, tokens, weekday, word_hits, workday, POS_WORDS,
)
from campaign_detector.synth import AnalysisSpec, CampaignSpec, TreeBuilder, human_analysis, md_campaign


def test_tokens() -> None:
    assert tokens("KDR_FEP_topHits_forMedChem.pptx") == ["kdr", "fep", "top", "hits", "for", "med", "chem", "pptx"]
    assert tokens("top10_final") == ["top", "10", "final"]
    assert tokens("lig017") == ["lig", "017"]
    assert word_hits("KDR_FEP_topHits_forMedChem.pptx", POS_WORDS) == {"top", "hits", "medchem"}


def test_markers_and_templates() -> None:
    assert has_version_marker("dG_summary_v3.xlsx") and not has_version_marker("prev3.txt")
    assert template_key("run_lig017") == "run_lig#" and template_key("lambda_0.50") == "lambda_#.#"
    assert is_templated("run_lig017") and not is_templated("analysis") and not is_templated("Fig3")


def test_id_tokens() -> None:
    assert id_tokens("lig017_rmsd.png") == {"lig017", "lig17"}
    assert id_tokens("run_lig012") == {"lig012", "lig12"}
    assert id_token("run_lig012") == "lig012" and id_token("analysis") is None


def test_id_tokens_accept_a_separator_but_keep_the_prefix() -> None:
    assert id_tokens("cmpd_017_rmsd_reps.png") == id_tokens("cmpd017") == {"cmpd017", "cmpd17"}
    assert id_tokens("lig-007.png") == {"lig007", "lig7"}
    assert not id_tokens("cmpd012_pose1.png") & id_tokens("run_lig012")  # B5 guard: prefix always kept
    assert id_token("cmpd_017") is None  # id_token (synth naming) is unchanged


@pytest.mark.parametrize("name, cls", [
    ("complex.prmtop", "TOPO"), ("prod.in", "INPUT"), ("prod001.nc", "TRAJ"), ("prod.rst7", "RESTART"),
    ("prod001.out", "LOG"), ("slurm-4100000.out", "SCHED"), ("job.o123", "SCHED"), ("fig3.png", "DERIVED"),
    ("submit_all.sh", "OTHER"),
])
def test_classify(name: str, cls: str) -> None:
    assert classify_name(name) == cls


def test_time_model() -> None:
    assert weekday(T0) == 0 and local_hour(T0) == 0 and era(T0) == 2020
    assert at(1, 9.5) == T0 + 86400 + 9 * 3600 + 1800
    assert [workday(k) for k in range(7)] == [0, 1, 2, 3, 4, 7, 8]
    assert workday(-5) == -7
    assert is_working_hours(at(2, 8)) and not is_working_hours(at(2, 18)) and not is_working_hours(at(5, 12))
    assert local_hour(at(0, 23), 3600) == 0 and weekday(at(0, 23), 3600) == 1


def _tree() -> dict:
    tb = TreeBuilder("/vol1")
    md_campaign(tb, "md", CampaignSpec(n_candidates=6, n_chunks=10, jitter_s=0))
    human_analysis(tb, "/vol1", AnalysisSpec())
    return all_features(tb.build())


def test_campaign_member_features() -> None:
    f = _tree()["/vol1/md/run_lig003"]
    assert f.traj_chunk_regularity == pytest.approx(1.0)
    assert f.traj_byte_fraction > 0.9
    assert f.md_class_coverage == 6 and f.engine == "amber" and f.traj_chunk_count == 10
    assert not f.traj_series_gap and f.uid_purity == 1.0 and f.dominant_uid == 2001
    assert "TRAJ:prod#.nc" in f.signature and f.name_is_templated


def test_human_dir_features() -> None:
    f = _tree()["/vol1/analysis"]
    assert f.working_hours_fraction >= 0.6 and f.weekend_fraction == 0.0
    assert f.derived_fraction == 1.0 and f.n_bursts == 3 and f.pos_word_score >= 1
    assert not f.name_is_templated and f.child_name_diversity == 1.0


def test_sibling_uniformity() -> None:
    tb = TreeBuilder("/vol1")
    md_campaign(tb, "md", CampaignSpec(n_candidates=6, n_chunks=4))
    human_analysis(tb, "md", AnalysisSpec())
    inv = tb.build()
    group, uni, frac, sig = sibling_uniformity(inv, all_features(inv), "/vol1/md")
    assert len(group) == 6 and uni == 1.0 and frac == pytest.approx(6 / 7)
    assert {s.split(":")[0] for s in sig} == {"TOPO", "INPUT", "TRAJ", "RESTART", "LOG", "SCHED"}


def test_jitter_lowers_regularity() -> None:
    tb = TreeBuilder("/vol1")
    md_campaign(tb, "md", CampaignSpec(n_candidates=4, n_chunks=10, jitter_s=5400))
    f = all_features(tb.build())["/vol1/md/run_lig001"]
    assert 0.4 < f.traj_chunk_regularity < 0.6
