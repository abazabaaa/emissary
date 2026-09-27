# campaign-detector

Prototype that reads a filesystem **inventory** (one row per file, directory or
symlink: path, kind, size, mtime, ctime, uid, gid, inode, nlink, optional
sha256, optional symlink target) of a long-lived scientific computing archive
and, without reading any file contents, answers three questions:

1. **Did a molecular-dynamics campaign happen here?** Machine fingerprint:
   many templated sibling directories (`run_lig001` ... `run_lig048`) each
   holding the same topology/input/trajectory-chunks/restart/log/scheduler
   files, chunks with evenly spaced mtimes at all hours from one uid, and
   trajectories dominating the bytes.
2. **Did a human curate the results?** An irregular directory with worded
   names (`final`, `top10`, `forMedChem`, `v3`), small derived files (`.png`,
   `.xlsx`, `.pptx`, `.ipynb`, `notes.txt`), written in working-hours bursts
   after the campaign, often by a different uid.
3. **Which candidates did the human pick?** Copies whose hash matches exactly
   one run directory, hard links, symlinks into one run directory, derived
   artifacts named after a candidate, and the candidate id reappearing later
   elsewhere. Selection must be a *subset*: links to nearly every candidate
   (mirror, symlink index, pipeline), boilerplate identical across candidates
   and copies into `old`/`bak`/`trash` directories are not picks.

Runtime is Python 3.11 standard library only; tests need `pytest`.

## Running it

```sh
cd contrib/campaign-detector
python3 -m pip install --user pytest   # or: pip install pytest
python3 -m pytest -q
python3 -m campaign_detector demo
python3 -m campaign_detector synth --scenario positive_amber_basic.kdr_fep --out /tmp/kdr.tsv
python3 -m campaign_detector detect --inventory /tmp/kdr.tsv
python3 -m campaign_detector detect --inventory /tmp/kdr.tsv --json
python3 -m campaign_detector features --inventory /tmp/kdr.tsv --out /tmp/kdr-features.tsv
python3 -m campaign_detector synth --list
```

`demo` prints `scenario | kind | expected | got | status` for every
registered scenario (70: 69 PASS and 1 XFAIL, see "Remaining known gaps"). Status is PASS/FAIL, or XFAIL/XPASS for scenarios with a
`known_gap`; it exits 1 on any FAIL or XPASS (an XPASS means the gap closed:
remove `known_gap`).

## The grounded scenario

`positive_amber_basic.kdr_fep`: an Amber relative-binding FEP campaign at
`/vol3/projects/KDR_2011/fep`, submitted Monday 2011-03-14 by uid 2001 via
`submit_all.sh`. 48 ligands `run_lig001`..`run_lig048`, of which lig017 and
lig033 never ran (46 exist); each run has `complex.prmtop`, `prod.in` (shared
boilerplate), 20 six-hourly 1.2 GB chunks `prod001.nc`..`prod020.nc` with
per-chunk `prodNNN.out`, `prod.rst7` and `slurm-<jobid>.out`. Three weeks
later uid 3002 works in `fep/analysis/` (`dG_summary_v3.xlsx`, `notes.txt`,
`KDR_FEP_topHits_forMedChem.pptx`, `README.md`, three bursts) and picks:

| candidate  | how                                                          |
|------------|--------------------------------------------------------------|
| run_lig012 | copy of `prod010.nc` renamed `analysis/lig012_bestpose.nc`   |
| run_lig029 | derived plots `lig029_rmsd.png`, `lig029_stable.png`         |
| run_lig041 | symlink `analysis/lig041_traj -> ../run_lig041/prod020.nc`   |

`analysis/old/lig005_prod010.nc` is a copy of run_lig005 inside a tainted
directory and must not count. Expected: exactly that campaign root; picked
{012, 029, 041}; the other 43 not_picked; missing ids run_lig017, run_lig033.

## Detection pipeline (`detect.detect`)

1. **Featurize** every directory (`features.all_features`). A Desmond
   `<job>_trj/` directory is part of the level that holds it: its `frame*`
   files and `clickme.dtr` are TRAJ and count at that level's depth, so the
   trajectory folds into its run.
2. **Campaign roots.** Directories are evaluated deepest first. `P`
   qualifies when the largest group `G` of child dirs sharing a
   `name_template` has at least `min_candidates` members, covers
   `template_fraction` of the child dirs, has signature `uniformity` >= 0.75,
   a modal signature with >= `min_md_classes` MD classes including TRAJ,
   aggregate trajectory byte fraction >= 0.5 and uid purity >= 0.9 over G's
   files (depth <= 2), a **topology** (`require_topology`: TOPO in the modal
   signature, or a TOPO file directly in `P`, in a non-member child dir such
   as `setup/`, or in `P`'s parent; no MD engine runs without one, while
   ocean/climate netCDF passes every other gate), and confidence
   `0.3*uniformity + 0.2*classes/6 + 0.2*traj_frac + 0.15*regularity + 0.15*purity`
   >= `campaign_conf`.
   **Batches** (`batch_subsets`): when `G` fails, every template group is
   tried again restricted to its members with the most common TRAJ-bearing
   signature. Such a batch skips the template-fraction gate but must pass
   every other gate and have one submitter (uid purity) and run windows
   that overlap or follow each other within `batch_max_gap_s` (7 days). A
   campaign is a batch of runs, and the name template is evidence of one,
   not its definition: four co-submitted runs among 26 unrelated
   `proj_###` folders, or an outnumbered `proj_###_md` group, are found; five
   runs by five people over five years are not.
   When `P` qualifies, roots found inside its members are discarded (a
   replica level such as `rep#` or `lambda_#.#` folds into its candidate)
   unless at least half of the members hold a non-replica root: then the
   members are campaigns in their own right (`batch1..batch4`) and `P` is
   not a root. A **replica-level root** that nothing absorbs is dropped when
   its own directory is one of >= 2 templated sibling runs
   (`drop_replica_roots`: three ligands x four replicas are three
   candidates, not three campaigns; a lone `clone_001..clone_024` stays).
   **Mirrors.** A root whose trajectory hashes are >= `copy_overlap` copies
   of another root's is a mirror/backup, not a campaign; the original is
   the root that ranks first by (not tainted relative to the other, more
   **provenance**, earlier chunk ctime). Provenance (`mirror_provenance`) is
   a submit/workflow script in the root or its parent, plus a non-member
   directory beside the runs (`analysis/` in the root or a sibling of it),
   so a working copy restored from its DR mirror (later ctimes, but the only
   one with `submit_all.sh` and `analysis/`) stays the campaign. The
   original gets a note.
   **Compute happened** (`min_run_span_s`): a root whose median member run
   window (first MD file to last trajectory chunk) is under one hour is
   dropped: a `cp -r` of course kits (every file carries the copy instant)
   or a screen that crashed minutes into its first chunk. Mirrors are split
   off before this gate, so a copy that did not keep mtimes is still
   recognised as a copy. `root_verdicts(inv)` reports, for every directory
   with >= `min_candidates` child dirs, `"root"` or the gate that rejected it.
3. **Taint.** A path with a `NEG_WORDS` token (`old`, `bak`, `trash`, ...)
   in any component below its common ancestor with the campaign root is
   never an evidence source or curated dir.
4. **Curated dirs** (per campaign): untainted dirs outside every candidate
   with >= 2 direct entries (files or symlinks) score one point each for an
   approval word or version marker in their name or in ancestor names below
   the campaign root's parent (the root's own name excluded), derived
   fraction >= 0.5, working-hours fraction >= 0.6 of entries, all entries
   newer than this campaign's last chunk (`t_end`), an owner other than the
   submitter, and an irregular non-templated name with child-name diversity
   >= 0.5. Score >= `curated_score` is curated, unless the **script-cadence
   veto** (`script_cadence`) fires: the dir is owned by the submitter and is
   written like the job's own output, either (a) first written within
   `script_onset_s` (1 h) after the campaign's last chunk *and* at least one
   entry per `script_density_s` (10 s), or (b) id-named files of >= 3
   candidates sit at the same offset (within 10 s) from each candidate's
   own last chunk (a per-job epilogue). Hard links are ignored by the veto
   (their mtime belongs to the inode). Either signal alone is ordinary for
   a person on the submitter's account and does not veto. The report notes
   every vetoed dir.
5. **Evidence** from the direct children of curated dirs: `hardlink` (1.0,
   shared inode with nlink > 1 and equal size, mtime and uid) else
   `copy_out` (1.0, sha256) when the file matches files of exactly one
   candidate; `symlink` (1.0) when the link's chain reaches exactly one
   candidate (followed hop by hop up to `symlink_max_hops`, stopping at a
   loop or a dangling end; the first path inside a candidate wins);
   `derived` (0.7) for a `DERIVED_EXTS` file newer than the campaign whose
   `id_tokens` intersect the candidate's, unless its hash occurs in >= 2
   candidates (`derived_uniqueness`: boilerplate named after the reference
   run) and only from a curated dir that is **local** to the campaign
   (`derived_locality`: on the root's volume and within the root's parent,
   `derived_locality_levels` = 1) or that also holds link evidence into it;
   `graduation` (0.5) for an untainted dir outside every campaign root,
   newer than the campaign, whose name carries the candidate id (global, and
   below the pick threshold alone); then the `Hooks` (their evidence must
   use a known kind, a candidate id of the report and a normalized absolute
   `src`, else `ValueError`).
6. **Coverage cap.** Per evidence kind, evidence units are "the files
   directly in dir D" and "everything below dir D". A unit's share is the
   larger of (candidates it names / all candidates) and, when some runs
   fell short but at least half and at least `min_candidates` finished,
   (completed runs it names / completed runs) (`cap_completed`; completed =
   the campaign's maximum chunk count). A unit covers when its share
   reaches `coverage_cap`, or when its share of all candidates is in the
   ambiguous band [`machine_band`, `coverage_cap`) = [0.5, 0.8) and it is
   machine-shaped: >= 90% of its byte copies keep the source basename, or it
   was written in one burst at a regular cadence in candidate-id order.
   Every minimal covering unit is dropped with a note; if what remains of
   that kind still reaches the cap it is dropped too.
7. **Labels.** Score = sum of weights; `picked` at >= `pick_threshold`,
   `unknown` below; with no pick every candidate is `unknown`, otherwise
   zero-evidence candidates are `not_picked`.
   `selection_confidence = mean(max weight per pick) * (1 - picks/candidates)`;
   below `selection_conf` all labels revert to `unknown` with a note. The
   comparison stays `<`: the human-shaped 70% shortlist
   (`positive_hardening_twins.human_shaped_70`) sits exactly on 0.30, and
   its machine-shaped twin is caught by step 6, not by this backstop.

### Hardening (unit C1): gaps, rules, knobs and guards

Every rule has a `Params` knob; switching it off reopens exactly the gaps
listed and nothing else (`tests/test_hardening.py` checks each knob and
pins, per negative, the gate that rejects every would-be root).

| gap (scenario) | rule | knob | guards that stay put |
|---|---|---|---|
| `negative_machine_bulk.roms_ensemble` | topology required | `require_topology` | `lidar_station` (still rejected by byte fraction), every positive |
| `negative_md_lookalikes.md_course_single_student`, `failed_screen_partial` | compute happened | `min_run_span_s` | `amber_examples`, `md_course`, `failed_screen`; `four_candidates_boundary` |
| `negative_copies.rsync_mirror` | mirror provenance before ctime | `mirror_provenance` | `mirror_backup`, `backup_only_analysis`, twin `mirror_snapshot_with_picks` |
| `negative_pathological.few_candidates_replicated` | replica-level roots of sibling runs are dropped | `drop_replica_roots` | `symlink_to_replica`, lambda/rep positives |
| `positive_pathological_links.numbered_siblings_md_subset`, `minority_template_campaign` | batches | `batch_subsets`, `batch_max_gap_s` | `numbered_siblings_heterogeneous` |
| `positive_gromacs_replicates.abl_md`, `positive_desmond_fep.kdr_fep_plus` | `id_tokens` accept `letters[_-]digits` | (vocabulary) | `docking_pose_same_numbers` (`cmpd012` never meets `lig012`) |
| `negative_mismatched.stem_collision`, `library_beside_unrelated_md`, `graduation_false_friend_summary` | derived locality | `derived_locality`, `derived_locality_levels` | twin `stem_collision_with_copy` (locality by evidence), `kdr_fep` |
| `negative_automation.reference_run_protocol_bundle` | derived uniqueness | `derived_uniqueness` | every derived positive |
| `positive_pathological_links.symlink_chain_pick` | symlink chains | `symlink_max_hops` | `symlink_pathology` |
| `negative_automation.submission_postprocess`, `per_job_epilogue_daytime` | script cadence | `script_cadence`, `script_onset_s`, `script_density_s` | twin `same_account_analysis`, every positive analysis dir |
| `negative_automation.qc_symlink_farm_two_thirds`, `negative_copies.coverage_cap_70` | coverage vs completed runs; machine-shaped band | `cap_completed`, `machine_band` | twin `human_shaped_70` |
| real Desmond layout (no scenario before) | `<job>_trj/frame*` is TRAJ, `.ene` is LOG | (classification) | twin `desmond_trj_fep` |

The coverage row's two negatives are each caught by either of its two rules alone.

## Remaining known gaps

- `positive_identity_graduation.kdr_then_abl` stays XFAIL on purpose.
  lig029's only trace is its InChIKey reappearing under another compound
  name in a later campaign; no inventory metadata carries identity.
  `content.detect_with_content` picks it (`tests/test_content_pipeline.py`).
- Limits of the new rules, not yet encoded as scenarios: a campaign whose
  median run lasts under an hour is not detected (`min_run_span_s`), even a
  genuine screen of very short runs; a copy that did not preserve mtimes is
  only recognised as a mirror when its original is in the inventory;
  derived-only picks from a curated dir two levels above the root need
  `derived_locality_levels=2` (the default follows the reviewed rule); a
  top-level root of `rep#`/`lambda_#` members that is itself one of
  several templated siblings is dropped even if the siblings are not runs.
- Scenario module docstrings (and their "Adversarial review" sections)
  describe the detector before hardening; the `known_gap` arguments were
  removed as each gap closed, and the tables above supersede those texts.

## Public API

### `campaign_detector.inventory`

- `KINDS` — entry kinds `("f", "d", "l")`.
- `COLUMNS` — TSV column order and `Entry` field order.
- `normalize_path(p)` — normalized absolute POSIX path; `ValueError` if relative.
- `Entry(path, kind, size, mtime, ctime, uid, gid, inode, nlink, sha256=None, target=None)` — frozen row; properties `name`, `parent` (`None` for `/`), `stem`, `ext`; `resolved_target()`.
- `Inventory(entries)` — strict collection (every entry but `/` needs its parent dir; no duplicates) with `by_path`, `by_sha`, `by_inode`, `children()`, `parent()`, `subtree()`, `dirs()`, `files()`, `links()`, iteration by path, `len`, `in`.
- `Inventory.from_tsv(src)` / `Inventory.to_tsv(dst)` — TSV with header, UTF-8 + `surrogateescape`, empty cell = `None`. Rows end at `\n` (or `\r\n`) only, so a carriage return inside a name round-trips; `to_tsv` refuses a last cell ending in `\r`.

### `campaign_detector.features`

- `T0`, `TZ_OFFSET_S`, `WORK_START_H`, `WORK_END_H` — integer time model constants (T0 = Monday 2020-09-07 UTC).
- `local_hour(ts, off)`, `weekday(ts, off)`, `is_working_hours(ts, off)`, `era(ts)` — time model.
- `at(day, hour, minute=0)`, `workday(k)` — synthetic calendar helpers (negative values go back in time).
- `POS_WORDS`, `NEG_WORDS`, `REPLICA_WORDS`, `DERIVED_EXTS`, `MD_CLASSES`, `MD_CLASS_NAMES`, `SCHED_RE`, `ENGINE_EXTS` — vocabularies.
- `tokens(name)`, `word_hits(name, words)`, `has_version_marker(name)`, `template_key(name)`, `is_templated(name)`, `id_tokens(name)`, `id_token(name)` — name analysis.
- `classify_name(name)`, `classify_path(path)`, `classify(entry)` — MD class of a file; `classify_path` knows Desmond `<job>_trj/frame*` (TRAJ), and compression suffixes in `COMPRESSION_EXTS` are stripped first. `is_trj_dir(name)`, `is_trj_frame(name)` — the Desmond trajectory-directory predicates.
- `engine_vote(files)`, `dominant(values)`, `chunk_index(entry)`, `chunk_regularity(chunks)`, `count_bursts(mtimes)`, `files_within(inv, path, max_depth=2)` (a `<job>_trj` dir does not consume depth), `jaccard(a, b)` — building blocks.
- `DirFeatures` — per-directory feature record (field docs in the class docstring).
- `dir_features(inv, path, *, tz_offset_s=0)`, `all_features(inv, *, tz_offset_s=0)` — featurizer.
- `sibling_uniformity(inv, feats, parent_path)` — `(group, uniformity, template_fraction, mode_sig)`.

### `campaign_detector.synth`

- `T0`, `at`, `workday` — re-exported time helpers.
- `TreeBuilder(root="/vol1", *, uid=1000, gid=1000, mtime=T0)` — `dir()`, `file()`, `symlink()`, `copy()`, `hardlink()`, `build()`.
- `CampaignSpec`, `ENGINE_PROFILES`, `md_campaign(tb, root, spec)` — MD campaign layout; returns candidate dir names. Profiles: `amber`, `gromacs`, `desmond` (synthetic `traj###.dcd`), `desmond_trj` (the real layout: `md-in.cms`, `md.msj`, `md.cfg`, `md_trj/frame###`, `md_trj/clickme.dtr`, `md-out.cms`, `md.ene`, `md.log`, `md.cpt`, `job.o<id>`), `namd`.
- `AnalysisSpec`, `human_analysis(tb, parent, spec)` — human analysis dir; returns its path.
- `pick_by_copy(tb, campaign_root, dst_dir, cids, ...)`, `pick_by_symlink(tb, dst_dir, campaign_root, cids, ...)`, `pick_by_derived(tb, dst_dir, cids, ...)` — selection fingerprints (note the argument order differs; pass by keyword if unsure).
- `ExpectedOutcome` with `no_campaign()`, `campaign_no_selection(root, cids=())`, `selection(root, picked, not_picked=(), unknown=(), rest=None)`.
- `Scenario(name, kind, description, build, expected, known_gap=None)`, `compare(expected, result)`, `LABELS`.

### `campaign_detector.detect`

- `Params` — thresholds (see the dataclass for defaults).
- `Evidence`, `Candidate`, `CuratedDir`, `CampaignReport` (`picked()`, `not_picked()`, `unknown()`), `DetectionResult` (`campaign_roots`, `to_dict()`).
- `EVIDENCE_KINDS`, `EVIDENCE_WEIGHTS` — evidence vocabulary.
- `Hooks(text_mentions=no_evidence, graduation=no_evidence)`, `EvidenceHook`, `no_evidence` — extension points.
- `is_within(path, ancestor)`, `is_tainted(path, anchor="/")` — path predicates.
- `detect(inv, *, params=None, hooks=None)` — run the pipeline.
- `root_verdicts(inv, *, params=None)` — `{dir: "root" | gate}` for every directory with >= `min_candidates` child dirs (gates: `template_fraction`, `uniformity`, `min_md_classes`, `no_traj`, `traj_byte_fraction`, `uid_purity`, `no_topology`, `campaign_conf`, `min_candidates`, `members_are_campaigns`, `absorbed_by:<root>`, `replica_level`, `mirror_copy`, `no_compute`; batch attempts follow as `|batch:<gate>`).

### `campaign_detector.scenarios` and `campaign_detector.cli`

- `register(*, kind, description, expected, known_gap=None, name=None)`, `all_scenarios()`, `get(name)` — scenario registry.
- `SUBCOMMANDS`, `main(argv=None)`, `format_report(report)`, `cmd_synth`, `cmd_detect`, `cmd_features`, `cmd_demo` — CLI.

### Synthetic conventions worth knowing

- Candidate ids are candidate **directory names** (`run_lig012`). Pick
  helpers name files with `{cid}` (dir name) or `{id}` (its id token,
  `lig012`): `pick_by_copy` default `rename="{id}_best.nc"`,
  `pick_by_symlink` default `link_name="{id}_traj"` (relative target),
  `pick_by_derived` writes `<id><suffix>`. The n-th item of one call gets
  `mtime + 60*n`.
- sha256 is `sha256(b"cd:" + content_id)`; `content_id` defaults to the
  file's path, so `tb.file(..., content_id=...)` models a `cp -p` copy
  (keep mtime, set a later `ctime`).
- Directory mtimes are derived on `build()` from their newest child; inodes
  count from 1000 in insertion order; `/` and every ancestor are emitted.
- Chunk files are 1-based (`prod001.nc`), so `src_name="prod010.nc"` needs
  `n_chunks >= 10`.

## Writing scenarios (for other teams)

- One module per group: `campaign_detector/scenarios/<kind>_<group>.py`
  where kind is `positive` or `negative`. Never edit a sibling module or the
  foundation modules; the registry discovers your module automatically.
- Decorate zero-argument `build_<short>()` functions with `@register(kind=...,
  description=..., expected=...)`; the scenario is named
  `<module>.<short>` (override `<short>` with `name=`).
- Express expectations with the `ExpectedOutcome` helpers:
  `no_campaign()`, `campaign_no_selection(root)`, `selection(root, picked,
  rest="not_picked")`. Negative scenarios must expect no picks; positive
  scenarios must expect at least one.
- If the detector gets a scenario wrong, keep the true expectation and set
  `known_gap="<heuristic>: <why>"` with heuristic one of `campaign_root`,
  `curated_dir`, `copy_out`, `hardlink`, `symlink`, `derived`, `graduation`,
  `coverage_cap`, `uniqueness`, `negwords`, `labels`. Tests mark it
  `xfail(strict=True)`; if it starts passing, remove the gap.
- No randomness, no wall-clock time (use `at()`/`workday()`), fewer than
  5,000 entries per scenario, stdlib only.
- `tests/conftest.py` parametrizes `scenario` (xfail-marked) and
  `declared_scenario` (unmarked) over every registered scenario.

## Contract deviations

- `word_hits` (used for `pos_word_score`, `neg_word_score` and taint) also
  matches two adjacent tokens joined, so `forMedChem` hits `medchem` and
  `BackUp` hits `backup`.
- `engine` is a majority vote over *distinct* extensions (not file counts),
  so ten `.dcd` chunks do not outvote Desmond's `.cms`/`.cfg`; ties go to
  amber, gromacs, desmond, namd in that order.
- Trajectory chunk series are grouped by (directory, name template);
  `traj_chunk_regularity` is the mean over series with >= 3 chunks and
  `traj_series_gap` is true if any series' distinct indices have a gap.
- `derived` evidence matches when the file's `id_tokens` *intersect* the
  candidate's (so `lig12_x.png` matches `run_lig012`).
- A file that is a hard link of a candidate file yields `hardlink` evidence
  only, not also `copy_out`.
- The coverage cap drops minimal covering subtrees before the per-kind
  global check (a superset of the per-directory rule that spares real picks
  when a mirror is split into per-candidate subdirectories).
- Added `Params.copy_overlap` and the mirror/backup gate in step 2.
- Step 2 does not let an outer directory absorb member directories that
  are campaigns in their own right (see the replica rule above).
- Taint looks only at components below the path's common ancestor with the
  campaign root, so campaigns under `/scratch` or `/tmp_projects` work.
- Curated-dir gating counts symlinks as entries, and the working-hours,
  newer-than-campaign and owner criteria use files and symlinks, so a
  folder of symlinks to the chosen runs is curated. `CuratedDir.n_files`
  is that entry count.
- The approval-word check excludes the campaign root's own name (a root
  called `fep_results` would otherwise vouch for every folder in it).
- Hard-link evidence also requires equal size, mtime and uid, because the
  inventory has no device column and inode numbers repeat across volumes.
- `ExpectedOutcome` has two extra fields: `rest` (per-root label for
  unlisted candidates, set by `selection(rest=...)`) and `present` (ids that
  must be candidates, set by `campaign_no_selection(root, cids)`).
- Pick helpers default to `{id}`-based names (`{id}_best.nc`, `{id}_traj`)
  and accept `{cid}` as well.
- `detect()` takes `params=None`/`hooks=None` meaning `Params()`/`Hooks()`.
- `Params.chunk_regularity` is advisory: below it the report gets a note;
  it does not gate the campaign.
- `missing_ids` is empty when the id range is more than ten times the number
  of candidates or the names differ outside their last digit run.
- Hardening (unit C1) adds `Params.require_topology`, `min_run_span_s`,
  `batch_subsets`, `batch_max_gap_s`, `drop_replica_roots`,
  `mirror_provenance`, `derived_locality`, `derived_locality_levels`,
  `derived_uniqueness`, `symlink_max_hops`, `script_cadence`,
  `script_onset_s`, `script_density_s`, `cap_completed` and `machine_band`
  (see the table in "Detection pipeline"), plus `root_verdicts()`.
- `id_tokens` accepts one `_` or `-` between the letters and the digits
  (`cmpd_017` and `lig-007` give `cmpd017`/`cmpd17`, `lig007`/`lig7`);
  `id_token` (used by the synthetic pick helpers to name files) is
  unchanged, so scenario builds are byte-identical.
- The campaign root's gates run in the order `min_candidates`,
  `template_fraction`, `uniformity`, `min_md_classes`, `no_traj`,
  `traj_byte_fraction`, `uid_purity`, `no_topology`, `campaign_conf`, so a
  scenario keeps the gate its reviewer documented.
- The mirror gate ranks by taint, provenance, then ctime (was ctime only);
  the note says "copies of this campaign's" rather than "later copies".
- `classify` looks at the path: files named `frame*` or `clickme.dtr` inside
  a `<job>_trj` directory are TRAJ; `.ene` is LOG and votes Desmond;
  `.tpr` is TOPO and votes GROMACS; `.gz`/`.bz2`/`.xz`/`.zst` are stripped
  before the extension is read (`.sdf.gz`, `.oeb.gz`, `.maegz` stay OTHER).
- The coverage cap may drop a unit below `coverage_cap` (completed-runs
  share, machine-shaped band); `tests/test_detect.py::
  test_broad_selection_reverts_to_unknown` now switches the band off to
  exercise the selection-confidence backstop alone.

## Real filesystems: materialize and walk

`campaign_detector.walker` proves the detector reads a real directory the
same way it reads a synthetic table, and is the crawler for a pilot on a
real NFS subtree.

```sh
python3 -m campaign_detector materialize --scenario positive_amber_basic.kdr_fep --dest /tmp/kdr_fs
python3 -m campaign_detector walk --root /tmp/kdr_fs --out /tmp/kdr_walked.tsv \
    --map-root /tmp/kdr_fs:/ --owners /tmp/kdr_fs.owners.tsv
python3 -m campaign_detector detect --inventory /tmp/kdr_walked.tsv   # same report as the synthetic TSV

# pilot on a real tree: no sidecar, optionally hash
python3 -m campaign_detector walk --root /nfs/projects/KDR --out kdr.tsv [--hash]
```

- `materialize(inv, dest, *, sparse=True) -> Manifest` writes `/vol3/...` to
  `<dest>/vol3/...`; `dest` must be missing or empty and stands for `/`.
  Files are sparse (`truncate` to the recorded size, so the 1.1 TB KDR tree
  takes ~200 KB); `sparse=False` writes deterministic bytes seeded by the
  recorded sha256 (copies stay byte-identical) and refuses files over
  64 MiB. Symlink targets are verbatim, files sharing inode, size, mtime
  and uid with `nlink > 1` become hard links (inode numbers repeat across
  volumes), and mtimes are set deepest first so directory mtimes survive.
- What an unprivileged process cannot set goes in the `Manifest` and in
  `<dest>.owners.tsv` (columns `path uid gid sha256 ctime`; read it with
  `load_owners`): owners, the recorded sha256 (a sparse file's real hash is
  just "zeros of this size") and ctime (always "now" on disk; the mirror
  gate in step 2 compares ctimes).
- `walk_fs(root, *, map_root=None, hash=False, owners=None,
  follow_symlinks=False, on_error=None) -> Inventory` opens every directory
  with `O_DIRECTORY|O_NOFOLLOW` relative to its parent's fd, lists it with
  `os.scandir(fd)` and stats entries relative to that fd without following
  symlinks, so a tree being modified cannot redirect the walk. Names are
  decoded with `surrogateescape`, `/` and every ancestor of the root are
  emitted (strict inventory), symlinks keep `os.readlink` verbatim with
  `size = len(target)`, and inode/nlink come from `lstat`.
  `map_root=(src, dst)` rewrites the on-disk prefix; ancestors above `dst`
  that have no disk counterpart are synthesised with inode 0. `hash=True`
  reads regular files in 1 MiB blocks (sparse files are read in full: do
  not hash a materialized campaign). `owners` (sidecar path, `Manifest`,
  or `{path: (uid, gid[, sha256[, ctime]])}`) overrides uid/gid/ctime and
  supplies sha256 when `hash` is off (a file that fails to hash gets none).
  `follow_symlinks=True` reports a link to a regular file as that file;
  links to directories always stay links, so the walk never leaves the root
  or visits a directory twice. A bind mount of an open ancestor is listed
  but not entered.
- Errors never abort the walk: an `OSError` opening or listing a directory
  (EACCES, ESTALE, EIO) skips its subtree, one on an entry skips the entry,
  and a name or symlink target holding a tab, newline or carriage return
  (not representable in the TSV) is skipped as `EINVAL`. Since hardening,
  `Inventory.from_tsv` ends rows at `\n` only, so a carriage return in a
  name would round-trip; the walker's exclusion of `\r` (and its comment
  in `walker.py`, outside this unit) is now merely conservative. Each goes to `on_error` (re-raise there to abort) and
  to the inventory's `walk_errors` list; the `walk` CLI prints them and
  exits 1 after writing the TSV. Sockets, fifos and devices are skipped.
- Round trip (`tests/test_walker.py`): the KDR scenario materialized and
  walked back equals the synthetic inventory on path, kind, size, mtime,
  uid, gid, target, sha256 and ctime for all 2,087 entries, hard-linked
  names share an inode, and `detect()` returns an identical `to_dict()`:
  root `/vol3/projects/KDR_2011/fep`, picks lig012/lig029/lig041, 43 not
  picked, missing lig017/lig033.

## Content readers (OpenEye / Schrödinger interface)

The detector reads metadata only. `campaign_detector.content` adds an
optional second pass that reads file *contents* through vendor-neutral,
per-file readers and feeds the facts back through `detect.Hooks`. Nothing in
the detector changes; with no content facts the result is identical to
`detect()`. No licensed toolkit is needed to run or test it: a `FakeReader`
serves facts that synthetic scenarios declare as sidecar TSVs.

```sh
python3 -m campaign_detector.content sidecar --scenario positive_identity_graduation.kdr_then_abl --out-dir /tmp/r_content
python3 -m campaign_detector synth --scenario positive_identity_graduation.kdr_then_abl --out /tmp/r.tsv
python3 -m campaign_detector detect --inventory /tmp/r.tsv                                      # inventory only: no pick
python3 -m campaign_detector.content detect --inventory /tmp/r.tsv --content-dir /tmp/r_content  # lig029 picked (graduation)
python3 -m campaign_detector.content winner --inventory /tmp/r.tsv --content-dir /tmp/r_content --out /tmp/winner.tsv
python3 -m campaign_detector.content manifest --inventory /tmp/r.tsv [--json]
```

Modules (all stdlib; `model.py` imports nothing else, so a reader service
can import it unchanged under `$SCHRODINGER/run python3` or an OpenEye venv):

- `model`: `FileRef(path, sha256, size, mtime, file_class, fmt,
  companions)`, `CandidateRecord` (root, candidate id, path, engine, era,
  times, label, `unit` ligand/edge/leg/unknown, `replicas`, `files` by
  class, global `key = "<root>::<id>"`), `LigandIdentity` (role, name,
  `inchikey`, `inchikey14`, smiles, scaffold, `canon`, stereo, confidence,
  source path/record), `Metric`, `Mention`, `ReaderResult`, the `Reader`
  protocol (`name`, `version`, `cost`, `can_read(ref)`, `read(ref)`), and
  the TSV helpers every content file uses (backslash escapes, empty = None).
- `manifest`: `classify_content(entry)` / `classify_content_name(name)` use
  their own table (the detector's `MD_CLASSES` stay untouched) with double
  suffixes (`.oeb.gz`, `.sdf.gz`, `.maegz`), name patterns (`*_pv.maegz`,
  `*-out.cms`, `*_out.fmp`, `multisim.log`) and Desmond `<job>_trj/`
  directories, which become **one** TRAJ ref (`desmond.trj_dir`, size = sum
  of its `frame*` files, companion `<job>-out.cms`).
  `candidate_records(inv, result)` walks every candidate at any depth.
- `registry`: `ReaderRegistry.register(reader, fmts=, engines=, priority=)`
  (`"*"` = any format), `for_file(ref, engine)`, `read_file`,
  `read_candidate(rec, max_cost=, cache=)`; a raising reader yields an error
  result (not cached). `StubReader`/`stub_registry()` record which planned
  service (`oe-reader`, `sdgr-reader`, `oss-reader`) takes which format.
- `cache`: `ResultCache` keyed by `(sha256 or path|size|mtime, reader,
  version)`; hits are re-bound to the requesting path; `save`/`load` write
  five `cache_*.tsv` files.
- `sidecar`: `SidecarBuilder.ligand/metric/mention(path, ...)`,
  `write(scenario_or_builder, out_dir)` writes `ligands.tsv`, `metrics.tsv`
  and `mentions.tsv` (sha256 copied from the inventory); `read(dir)`.
  `fake_inchikey(smiles)` is 14 letters from `sha256("ik1:" + SMILES without
  @ / \)`, a hyphen, 8 letters from `sha256("ik2:" + SMILES)`, then `SA-N`,
  so stereo variants share `inchikey14` as real keys do.
- `fake`: `FakeReader(content_dir)` accepts a file whose path (with a
  matching sha) or sha256 the sidecars declare; deterministic.
- `aggregate`: `aggregate(rec, results) -> CandidateContent` uses only files
  inside the candidate; best identity by confidence, then support, then key;
  flags `identity_agree`, `multiple_ligands`, `no_identity`; metric means.
- `graduation`: `GraduationIndex.build(inv, result, contents, loose)` and
  `.hook(strong=1.0, weak=0.5)` for `Hooks.graduation`. Evidence is emitted
  when a candidate's InChIKey reappears **later** (occurrence time > the
  campaign's `t_end`; occurrences in a campaign use that campaign's
  `t_start`), **outside** the campaign root, **untainted** (`is_tainted`
  against the root, so `backup/`, `bak/`, `old/` never count) and **not as
  a byte copy** of a campaign file. Full-key matches with medium or high
  confidence on both sides weigh `strong`; connectivity-block-only or
  low-confidence matches weigh `weak` (below the pick threshold). The
  coverage cap drops a re-run of every ligand.
- `mentions`: `MentionIndex.hook(weight=0.7)` for `Hooks.text_mentions`
  emits one `text_mention` per (document, candidate) for documents directly
  in a curated dir of the campaign, matching `candidate_id` tokens,
  `inchikey`, `compound_id` (ligand name) or `smiles`.
- `pipeline`: `detect_with_content(inv, content_dir, *, params=None,
  registry=None, cache=None) -> DetectionResult` and `run_content(inv,
  registry, ...) -> ContentRun` (records, results, loose results, contents,
  indexes). Pass 1 runs `detect`; candidate files and loose
  STRUCT/RESULT/DERIVED files outside candidates are read and aggregated;
  the indexes are built; pass 2 runs `detect` with the hooks.
- `winner`: `winner_rows(result, aggregates, *, records=None,
  include_unknown=True)` and `write_winner_tsv` give identity, `meta_*`
  inventory features and `content_*` metrics. Leakage exclusions (tested):
  no metric read outside the candidate dir or from a curated dir, no `exp_*`
  metric (`exp_dg` is a label proxy), no score or evidence columns.

Identity scenarios (a module-level `CONTENT = {short: builder}` declares
their sidecar facts):

| scenario | registry expectation (`detect`) | `detect_with_content` |
|---|---|---|
| `positive_identity_graduation.kdr_then_abl` | lig029 picked with `known_gap` graduation (XFAIL by design: identity is invisible to metadata; the one gap hardening leaves open) | lig029 picked via ABL_2013 `cpd03` (same InChIKey, new name) |
| `positive_identity_graduation.kdr_then_abl_copyout` | lig012, lig041 picked (copy-out) | also lig029 (graduation) and lig035 (`notes.txt` mention) |
| `negative_identity.rerun_all` | no picks | no picks: all 46 keys re-run in 2014, coverage cap |
| `negative_identity.in_backup` | no picks | no picks: keys only under `backup/` and `bak/` |
| `negative_identity.earlier` | no picks | no picks: keys only in an earlier pilot campaign and docking list |

The content answers live in `positive_identity_graduation.CONTENT_EXPECTED`
and are checked by `tests/test_content_pipeline.py`. A positive scenario
must declare picks, so `kdr_then_abl` registers its true answer with a
known gap instead of the inventory-only "no pick".

Desmond layouts: the synthetic `desmond` profile writes `traj###.dcd`; the
`desmond_trj` profile writes the real `<job>_trj/frame*` layout, which the
detector now reads as TRAJ folded into its run
(`positive_hardening_twins.desmond_trj_fep`), as the content manifest does.
