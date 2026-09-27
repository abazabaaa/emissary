"""Hardening rules (unit C1): each rule, its guard, and which gate rejects every would-be root.

``GATES`` pins, for every negative scenario that must report no campaign, the
gate that rejects each directory the detector evaluates as a root
(:func:`campaign_detector.detect.root_verdicts`). A scenario that starts
failing for a different reason than its reviewer documented shows up here
even while the registry comparison still passes.
"""

from __future__ import annotations

import dataclasses

import pytest

from campaign_detector.detect import Params, detect, root_verdicts
from campaign_detector.scenarios import all_scenarios, get
from campaign_detector.scenarios.negative_pathological import misc_project
from campaign_detector.synth import CampaignSpec, TreeBuilder, at, md_campaign

GATES: dict[str, dict[str, str]] = {
    "negative_machine_bulk.lidar_station": {"/data/obs/halo_lidar/2019": "traj_byte_fraction"},
    "negative_machine_bulk.log_rotation": {"/vol4/ops/weblogs/2021Q1": "min_md_classes"},
    # No MD class at all: every signature is empty, so uniformity (Jaccard of empty sets) is 0 first.
    "negative_machine_bulk.ms_runs": {"/vol6/proteomics/plasma_2016/export": "uniformity"},
    "negative_machine_bulk.qm_confsearch": {"/vol5/qm/BRD4_confsearch_2019/dft_opt": "no_traj"},
    "negative_machine_bulk.roms_ensemble": {"/vol7/ocean/NWA_ensemble_2018/runs": "no_topology"},
    "negative_md_lookalikes.amber_examples": {"/opt/amber18/examples": "traj_byte_fraction"},
    "negative_md_lookalikes.failed_screen": {"/scratch/awad/EGFR_prescreen/runs": "traj_byte_fraction"},
    "negative_md_lookalikes.failed_screen_partial": {"/scratch/awad/EGFR_prescreen_v2/runs": "no_compute"},
    "negative_md_lookalikes.gromacs_regressiontests": {
        "/data/software/gromacs/regressiontests-2018/complex": "min_candidates",
        "/data/software/gromacs/regressiontests-2018/simple": "min_candidates",
    },
    "negative_md_lookalikes.md_course": {"/home/courses/md_course_2015": "uid_purity"},
    "negative_md_lookalikes.md_course_single_student": {"/home/mchen/md_course_2015": "no_compute"},
    "negative_md_lookalikes.oneoff_run": {"/vol4/adhoc/BRD4_probe": "min_candidates"},
    "negative_mismatched.docking_only_campaign": {"/vol8/docking_campaigns/vs_run7": "no_traj"},
    "negative_mismatched.no_campaign": {},
    "negative_pathological.dated_meeting_notes": {"/vol8/shared/meeting_notes": "uniformity"},
    "negative_pathological.dated_meeting_notes_with_structures": {"/vol8/shared/project_meetings": "uniformity"},
    "negative_pathological.deep_chain_arbitrary": {},
    "negative_pathological.deep_chain_templated": {},
    "negative_pathological.few_candidates_replicated": {
        "/vol4/legacy/tiny_replicas/data": "min_candidates",
        "/vol4/legacy/tiny_replicas/data/run_x001": "replica_level",
        "/vol4/legacy/tiny_replicas/data/run_x002": "replica_level",
        "/vol4/legacy/tiny_replicas/data/run_x003": "replica_level",
    },
    "negative_pathological.few_candidates_with_pick": {"/vol4/legacy/tiny_campaign/data": "min_candidates"},
    "negative_pathological.huge_flat_mixed": {},
    "negative_pathological.numbered_siblings_heterogeneous": {"/vol2/archive/proj_pool": "uniformity|batch:uid_purity"},
}


def test_gate_table_covers_every_no_campaign_negative() -> None:
    names = {s.name for s in all_scenarios() if s.kind == "negative" and not s.expected.campaign_roots}
    assert names == set(GATES)


@pytest.mark.parametrize("name", sorted(GATES))
def test_which_gate_rejects_each_would_be_root(name: str) -> None:
    assert root_verdicts(get(name).build()) == GATES[name]


def _off(**changes: object) -> Params:
    return dataclasses.replace(Params(), **changes)


# -- campaign root rules ------------------------------------------------------


def test_topology_gate_is_what_keeps_the_ocean_ensemble_out() -> None:
    inv = get("negative_machine_bulk.roms_ensemble").build()
    assert detect(inv).campaigns == []
    assert detect(inv, params=_off(require_topology=False)).campaign_roots == ["/vol7/ocean/NWA_ensemble_2018/runs"]


def test_shared_topology_in_the_root_satisfies_the_topology_gate() -> None:
    tb = TreeBuilder("/vol1")
    md_campaign(tb, "fep", CampaignSpec(n_candidates=6, n_chunks=6))
    inv = tb.build()
    stripped = TreeBuilder("/vol1")
    for e in inv:
        if e.kind == "f" and not e.name.endswith(".prmtop"):
            stripped.file(e.path, size=e.size, mtime=e.mtime, uid=e.uid)
    assert detect(stripped.build()).campaigns == []  # no topology anywhere
    stripped.file("/vol1/fep/complex.prmtop", size=4_000_000, mtime=at(0, 2), uid=2001)
    assert detect(stripped.build()).campaign_roots == ["/vol1/fep"]


@pytest.mark.parametrize("name", ["negative_md_lookalikes.md_course_single_student",
                                  "negative_md_lookalikes.failed_screen_partial"])
def test_compute_happened_gate(name: str) -> None:
    inv = get(name).build()
    assert detect(inv).campaigns == []
    assert len(detect(inv, params=_off(min_run_span_s=0)).campaigns) == 1


def test_mirror_provenance_outranks_ctime() -> None:
    inv = get("negative_copies.rsync_mirror").build()
    assert detect(inv).campaign_roots == ["/vol9/site1/PROJ_2013/dock"]
    assert detect(inv, params=_off(mirror_provenance=False)).campaign_roots == ["/vol9/site2/PROJ_2013/dock"]
    verdicts = root_verdicts(get("negative_copies.mirror_backup").build())
    assert verdicts["/vol7/backup/2012-03/ABT_2012/md"] == "mirror_copy"  # guard: ties still go by ctime/taint


def test_replica_level_roots_are_never_campaigns() -> None:
    inv = get("negative_pathological.few_candidates_replicated").build()
    assert detect(inv).campaigns == []
    assert len(detect(inv, params=_off(drop_replica_roots=False)).campaigns) == 3


def _pool_with_runs(starts: list[int], uid_of: list[int]) -> TreeBuilder:
    tb = TreeBuilder("/vol2")
    root = "/vol2/pool"
    for i in range(5, 31):
        misc_project(tb, root, i)
    for n, (start, uid) in enumerate(zip(starts, uid_of), start=1):
        md_campaign(tb, root, CampaignSpec(n_candidates=n, candidate_fmt="proj_{:03d}", n_chunks=6, uid=uid,
                                           start=start, skip=frozenset(range(1, n))))
    return tb


def test_batch_subset_needs_one_submitter_and_one_time_window() -> None:
    together = _pool_with_runs([at(100, 3) + 900 * k for k in range(4)], [2101] * 4).build()
    assert detect(together).campaign_roots == ["/vol2/pool"]
    assert detect(together, params=_off(batch_subsets=False)).campaigns == []
    apart = _pool_with_runs([at(100 + 400 * k, 3) for k in range(4)], [2101] * 4).build()
    assert detect(apart).campaigns == []
    assert root_verdicts(apart)["/vol2/pool"].endswith("batch:batch_not_cotemporal")
    many_hands = _pool_with_runs([at(100, 3) + 900 * k for k in range(4)], [2101, 2102, 2103, 2104]).build()
    assert root_verdicts(many_hands)["/vol2/pool"].endswith("batch:uid_purity")


# -- evidence rules -------------------------------------------------------------


@pytest.mark.parametrize("name", ["negative_mismatched.stem_collision",
                                  "negative_mismatched.library_beside_unrelated_md",
                                  "negative_mismatched.graduation_false_friend_summary"])
def test_derived_locality(name: str) -> None:
    inv = get(name).build()
    assert not any(r.picked() for r in detect(inv).campaigns)
    assert any(r.picked() for r in detect(inv, params=_off(derived_locality=False)).campaigns)


def test_graduation_alone_stays_unknown_after_locality() -> None:
    (rep,) = detect(get("negative_mismatched.graduation_false_friend_summary").build()).campaigns
    lig = next(c for c in rep.candidates if c.id == "run_lig012")
    assert [e.kind for e in lig.evidence] == ["graduation"] and lig.label == "unknown"


def test_derived_boilerplate_is_not_evidence() -> None:
    inv = get("negative_automation.reference_run_protocol_bundle").build()
    assert not detect(inv).campaigns[0].picked()
    assert detect(inv, params=_off(derived_uniqueness=False)).campaigns[0].picked() == {"run_lig001"}


def test_symlink_chains_are_followed_with_a_hop_limit() -> None:
    inv = get("positive_pathological_links.symlink_chain_pick").build()
    (rep,) = detect(inv).campaigns
    assert rep.picked() == {"run_cpd003"}
    assert not detect(inv, params=_off(symlink_max_hops=9)).campaigns[0].picked()  # the chain has 10 hops
    (guard,) = detect(get("negative_pathological.symlink_pathology").build()).campaigns
    assert all(not c.evidence for c in guard.candidates)  # loops, dangling ends, never-run candidate


# -- script cadence -------------------------------------------------------------

_SUB = CampaignSpec()  # 24 amber runs, 10 x 6 h chunks, 15 min stagger, uid 2001


def _last_chunk(i: int) -> int:
    return _SUB.start + (i - 1) * _SUB.stagger_s + (_SUB.n_chunks - 1) * _SUB.chunk_interval_s


def _submitter_dir(times: dict[str, int]) -> tuple[list[str], list[str]]:
    """Campaign plus ``md/analysis_final`` written by the submitter at ``times`` (name -> mtime)."""
    tb = TreeBuilder("/vol1")
    md_campaign(tb, "/vol1/p/md", _SUB)
    for name, t in times.items():
        tb.file(f"/vol1/p/md/analysis_final/{name}", size=40_000, mtime=t, uid=_SUB.uid)
    (rep,) = detect(tb.build()).campaigns
    return sorted(rep.picked()), rep.notes


T_END = _last_chunk(24)
DAYS_LATER = at(20, 10)  # a weekday, 10:00


def test_same_account_human_stays_curated() -> None:
    picked, _ = _submitter_dir({"lig003_rmsd.png": DAYS_LATER, "notes.txt": DAYS_LATER + 1500,
                                "lig011_rmsd.png": DAYS_LATER + 3000})
    assert picked == ["run_lig003", "run_lig011"]
    # A plan written before the submission does not make the folder the job's own output.
    picked, _ = _submitter_dir({"plan.md": _SUB.start - 86400, "lig003_rmsd.png": DAYS_LATER,
                                "notes.txt": DAYS_LATER + 1500, "lig011_rmsd.png": DAYS_LATER + 3000})
    assert picked == ["run_lig003", "run_lig011"]


@pytest.mark.parametrize("times", [
    # starts 20 minutes after the last chunk, but writes by hand over the afternoon
    {"lig003_rmsd.png": T_END + 1200, "notes.txt": T_END + 5400, "lig011_rmsd.png": T_END + 9000},
    # one shell loop weeks later (ln -s / cp of the chosen few)
    {"lig003_rmsd.png": DAYS_LATER, "notes.txt": DAYS_LATER + 1, "lig011_rmsd.png": DAYS_LATER + 2},
])
def test_onset_or_density_alone_is_a_person(times: dict[str, int]) -> None:
    picked, notes = _submitter_dir(times)
    assert picked == ["run_lig003", "run_lig011"] and not any("not curated" in n for n in notes)


@pytest.mark.parametrize("times, signal", [
    ({"lig003_rmsd.png": T_END + 180, "notes.txt": T_END + 181, "lig011_rmsd.png": T_END + 182},
     "first write 180 s after the campaign's last chunk, 3 entries within 2 s"),
    ({f"lig{i:03d}_dG.png": _last_chunk(i) + 7200 for i in (22, 23, 24)} | {"notes.txt": DAYS_LATER},
     "after their own run's last chunk"),
])
def test_script_shaped_submitter_dir_is_not_curated(times: dict[str, int], signal: str) -> None:
    picked, notes = _submitter_dir(times)
    assert picked == []
    assert any("not curated" in n and signal in n for n in notes)


# -- coverage: completed runs and the machine-shaped band ----------------------


@pytest.mark.parametrize("name", ["negative_automation.qc_symlink_farm_two_thirds", "negative_copies.coverage_cap_70"])
def test_each_coverage_rule_alone_catches_the_finished_runs_farm(name: str) -> None:
    inv = get(name).build()
    for params in (Params(), _off(cap_completed=False), _off(machine_band=1.0)):
        assert not detect(inv, params=params).campaigns[0].picked()
    assert detect(inv, params=_off(cap_completed=False, machine_band=1.0)).campaigns[0].picked()


def test_completed_runs_share_is_reported() -> None:
    (rep,) = detect(get("negative_automation.qc_symlink_farm_two_thirds").build()).campaigns
    assert any("dropped 16 symlink links" in n and "covers 100%" in n for n in rep.notes)


# -- Desmond layout and file names ----------------------------------------------


@pytest.mark.parametrize("path, cls", [
    ("/r/lig001/lambda_0.00/md_trj/frame001", "TRAJ"),
    ("/r/lig001/md_trj/clickme.dtr", "TRAJ"),
    ("/r/lig001/md_trj/metadata", "OTHER"),
    ("/r/lig001/frame001", "OTHER"),  # a frame outside a _trj dir is not a trajectory
    ("/r/lig001/md.ene", "LOG"),
    ("/r/lig001/md-out.cms", "TOPO"),
    ("/r/lig001/complex.prmtop.gz", "TOPO"),
    ("/r/poses/hits.sdf.gz", "OTHER"),
    ("/r/poses/hits.oeb.gz", "OTHER"),
    ("/r/poses/dock_pv.maegz", "OTHER"),
    ("/r/archive/run_pose001.tar.gz", "OTHER"),
    ("/r/qm/conf001/opt_trj.xyz", "OTHER"),  # an _trj *file* stays what its extension says
])
def test_classify_paths(path: str, cls: str) -> None:
    from campaign_detector.features import classify_path

    assert classify_path(path) == cls


def test_desmond_trj_frames_fold_into_their_run(monkeypatch: pytest.MonkeyPatch) -> None:
    import campaign_detector.features as features

    inv = get("positive_hardening_twins.desmond_trj_fep").build()
    (rep,) = detect(inv).campaigns
    assert rep.engine == "desmond" and rep.n_candidates == 16
    assert all(c.features.traj_chunk_count == 4 * 8 for c in rep.candidates)  # 4 lambda windows x 8 frames
    monkeypatch.setattr(features, "is_trj_dir", lambda name: False)
    assert detect(inv).campaigns == []  # before the rule: frames were OTHER and no root was found


def test_human_shaped_70_is_not_machine_shaped() -> None:
    (rep,) = detect(get("positive_hardening_twins.human_shaped_70").build()).campaigns
    assert len(rep.picked()) == 21 and rep.selection_confidence == pytest.approx(0.3)
    assert not any("machine-shaped" in n for n in rep.notes)


def test_stem_collision_twin_needs_the_copy() -> None:
    reports = {r.root: r for r in detect(get("positive_hardening_twins.stem_collision_with_copy").build()).campaigns}
    kdr = reports["/vol2/projects/KDR_2011/fep"]
    assert {c.id: sorted(e.kind for e in c.evidence) for c in kdr.candidates if c.evidence} == {
        "run_lig029": ["copy_out", "derived"], "run_lig033": ["derived"]}


EXTENDED = (3, 9, 15, 21)


def test_extended_minority_is_not_the_completed_set() -> None:
    """Four runs extended to 14 chunks (by the person who then keeps them) are a pick, not 'what finished'."""
    tb = TreeBuilder("/vol1")
    md_campaign(tb, "/vol1/p/md", CampaignSpec(n_candidates=24, n_chunks=10, skip=frozenset(EXTENDED)))
    md_campaign(tb, "/vol1/p/md", CampaignSpec(n_candidates=24, n_chunks=14,
                                               skip=frozenset(range(1, 25)) - set(EXTENDED)))
    for n, i in enumerate(EXTENDED):
        tb.copy(f"/vol1/p/md/run_lig{i:03d}/prod014.nc", f"/vol1/p/analysis/lig{i:03d}_keep_v{n}.nc",
                mtime=at(20 + 2 * n, 11), uid=3002)
    tb.file("/vol1/p/analysis/notes.txt", size=3_000, mtime=at(21, 15), uid=3002)
    (rep,) = detect(tb.build()).campaigns
    assert rep.picked() == {f"run_lig{i:03d}" for i in EXTENDED}


# -- review guards ----------------------------------------------------------------


def test_a_lone_clone_campaign_is_not_a_replica_level() -> None:
    tb = TreeBuilder("/vol3")
    md_campaign(tb, "/vol3/ab/md", CampaignSpec(n_candidates=24, candidate_fmt="clone_{:03d}", n_chunks=6))
    assert detect(tb.build()).campaign_roots == ["/vol3/ab/md"]


def test_topology_in_a_tpr_or_a_shared_setup_dir() -> None:
    tb = TreeBuilder("/vol1")
    for i in range(1, 7):
        run = f"/vol1/gmx/run{i:02d}"
        tb.file(f"{run}/topol.tpr", size=3_000_000, mtime=at(0, 2), uid=2001)
        tb.file(f"{run}/md.log", size=50_000, mtime=at(1, 2), uid=2001)
        for k in range(1, 7):
            tb.file(f"{run}/traj{k:03d}.xtc", size=900_000_000, mtime=at(0, 3) + k * 21600, uid=2001)
    assert detect(tb.build()).campaign_roots == ["/vol1/gmx"]  # .tpr is a topology
    tb = TreeBuilder("/vol1")
    names = md_campaign(tb, "/vol1/fep", CampaignSpec(n_candidates=6, n_chunks=6))
    inv = tb.build()
    moved = TreeBuilder("/vol1")
    for e in inv:
        if e.kind == "f" and e.name != "complex.prmtop":
            moved.file(e.path, size=e.size, mtime=e.mtime, uid=e.uid)
    moved.file("/vol1/fep/setup/complex.prmtop", size=4_000_000, mtime=at(0, 2), uid=2001)
    assert detect(moved.build()).campaign_roots == ["/vol1/fep"] and len(names) == 6


def test_a_later_copy_with_its_own_script_does_not_outrank_the_original() -> None:
    tb = TreeBuilder("/vol5")
    md_campaign(tb, "/vol5/lab/proj/md", CampaignSpec(n_candidates=8, n_chunks=6))
    tb.file("/vol5/lab/proj/submit_all.sh", size=1_500, mtime=at(0, 2), uid=2001)
    snap = tb.build()
    for e in snap.subtree("/vol5/lab/proj/md"):
        if e.kind == "f":
            tb.file("/vol5/home/stu/course/md" + e.path[len("/vol5/lab/proj/md"):], size=e.size, mtime=e.mtime,
                    uid=e.uid, content_id=e.path, ctime=at(300, 10))
    tb.file("/vol5/home/stu/course/md/rerun.sh", size=900, mtime=at(300, 11), uid=4100)
    assert detect(tb.build()).campaign_roots == ["/vol5/lab/proj/md"]


def test_ln_s_of_run_dirs_keeps_names_but_is_not_a_mirror() -> None:
    """7 of 12 finished runs (24 total) symlinked by name over several days: 29% of candidates, a pick."""
    tb = TreeBuilder("/vol1")
    crashed = frozenset(range(2, 25, 2))
    md_campaign(tb, "/vol1/p/dock", CampaignSpec(n_candidates=24, n_chunks=10, skip=crashed))
    md_campaign(tb, "/vol1/p/dock", CampaignSpec(n_candidates=24, n_chunks=4, skip=frozenset(range(1, 25)) - crashed))
    chosen = (17, 3, 21, 9, 13, 1, 23)
    for n, i in enumerate(chosen):
        tb.symlink(f"/vol1/p/selected/run_lig{i:03d}", f"../dock/run_lig{i:03d}", mtime=at(20 + n, 11 + n % 3),
                   uid=3002)
    tb.file("/vol1/p/selected/notes.txt", size=2_000, mtime=at(22, 16), uid=3002)
    (rep,) = detect(tb.build()).campaigns
    assert rep.picked() == {f"run_lig{i:03d}" for i in chosen}


def test_locality_radius_is_a_parameter() -> None:
    tb = TreeBuilder("/vol1")
    md_campaign(tb, "/vol1/proj/md/production", CampaignSpec(n_candidates=12, n_chunks=6))
    for n, name in enumerate(("lig007_rmsd.png", "notes.txt", "summary_v2.xlsx")):
        tb.file(f"/vol1/proj/analysis/{name}", size=40_000, mtime=at(20 + n, 11), uid=3002)
    inv = tb.build()
    assert not detect(inv).campaigns[0].picked()  # two levels up and derived-only: not local by default
    assert detect(inv, params=_off(derived_locality_levels=2)).campaigns[0].picked() == {"run_lig007"}
