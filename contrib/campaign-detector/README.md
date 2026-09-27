# campaign-detector

Prototype that reads a filesystem **inventory** (one row per file, directory or
symlink: path, kind, size, mtime, ctime, uid, gid, inode, nlink, optional
sha256, optional symlink target) of a long-lived CADD/cheminformatics archive
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
registered scenario. Status is PASS/FAIL, or XFAIL/XPASS for scenarios with a
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

1. **Featurize** every directory (`features.all_features`).
2. **Campaign roots.** Directories are evaluated deepest first. `P`
   qualifies when the largest group `G` of child dirs sharing a
   `name_template` has at least `min_candidates` members, covers
   `template_fraction` of the child dirs, has signature `uniformity` >= 0.75,
   a modal signature with >= `min_md_classes` MD classes including TRAJ,
   aggregate trajectory byte fraction >= 0.5 and uid purity >= 0.9 over G's
   files (depth <= 2), and confidence
   `0.3*uniformity + 0.2*classes/6 + 0.2*traj_frac + 0.15*regularity + 0.15*purity`
   >= `campaign_conf`. When `P` qualifies, roots found inside its members are
   discarded (a replica level such as `rep#` or `lambda_#.#` folds into its
   candidate) unless at least half of the members hold a non-replica root:
   then the members are campaigns in their own right (`batch1..batch4`) and
   `P` is not a root. A root whose trajectory hashes are >= `copy_overlap`
   later copies (by ctime) of another root's is a mirror/backup, not a
   campaign; the original gets a note.
3. **Taint.** A path with a `NEG_WORDS` token (`old`, `bak`, `trash`, ...)
   in any component below its common ancestor with the campaign root is
   never an evidence source or curated dir.
4. **Curated dirs** (per campaign): untainted dirs outside every candidate
   with >= 2 direct entries (files or symlinks) score one point each for an
   approval word or version marker in their name or in ancestor names below
   the campaign root's parent (the root's own name excluded), derived
   fraction >= 0.5, working-hours fraction >= 0.6 of entries, all entries
   newer than the last chunk, an owner other than the submitter, and an
   irregular non-templated name with child-name diversity >= 0.5. Score >=
   `curated_score` is curated.
5. **Evidence** from the direct children of curated dirs: `hardlink` (1.0,
   shared inode with nlink > 1 and equal size, mtime and uid) else
   `copy_out` (1.0, sha256) when the file
   matches files of exactly one candidate; `symlink` (1.0) when the resolved
   target lies in exactly one candidate; `derived` (0.7) for a
   `DERIVED_EXTS` file newer than the campaign whose `id_tokens` intersect the
   candidate's; `graduation` (0.5) for an untainted dir outside every campaign
   root, newer than the campaign, whose name carries the candidate id; then
   the `Hooks` (their evidence must use a known kind, a candidate id of the
   report and a normalized absolute `src`, else `ValueError`).
6. **Coverage cap.** Per evidence kind, evidence units are "the files
   directly in dir D" and "everything below dir D". Every minimal unit whose
   distinct candidates reach `coverage_cap` of the campaign is dropped with a
   note; if what remains of that kind still reaches the cap it is dropped too.
7. **Labels.** Score = sum of weights; `picked` at >= `pick_threshold`,
   `unknown` below; with no pick every candidate is `unknown`, otherwise
   zero-evidence candidates are `not_picked`.
   `selection_confidence = mean(max weight per pick) * (1 - picks/candidates)`;
   below `selection_conf` all labels revert to `unknown` with a note.

## Public API

### `campaign_detector.inventory`

- `KINDS` — entry kinds `("f", "d", "l")`.
- `COLUMNS` — TSV column order and `Entry` field order.
- `normalize_path(p)` — normalized absolute POSIX path; `ValueError` if relative.
- `Entry(path, kind, size, mtime, ctime, uid, gid, inode, nlink, sha256=None, target=None)` — frozen row; properties `name`, `parent` (`None` for `/`), `stem`, `ext`; `resolved_target()`.
- `Inventory(entries)` — strict collection (every entry but `/` needs its parent dir; no duplicates) with `by_path`, `by_sha`, `by_inode`, `children()`, `parent()`, `subtree()`, `dirs()`, `files()`, `links()`, iteration by path, `len`, `in`.
- `Inventory.from_tsv(src)` / `Inventory.to_tsv(dst)` — TSV with header, UTF-8 + `surrogateescape`, empty cell = `None`.

### `campaign_detector.features`

- `T0`, `TZ_OFFSET_S`, `WORK_START_H`, `WORK_END_H` — integer time model constants (T0 = Monday 2020-09-07 UTC).
- `local_hour(ts, off)`, `weekday(ts, off)`, `is_working_hours(ts, off)`, `era(ts)` — time model.
- `at(day, hour, minute=0)`, `workday(k)` — synthetic calendar helpers (negative values go back in time).
- `POS_WORDS`, `NEG_WORDS`, `REPLICA_WORDS`, `DERIVED_EXTS`, `MD_CLASSES`, `MD_CLASS_NAMES`, `SCHED_RE`, `ENGINE_EXTS` — vocabularies.
- `tokens(name)`, `word_hits(name, words)`, `has_version_marker(name)`, `template_key(name)`, `is_templated(name)`, `id_tokens(name)`, `id_token(name)` — name analysis.
- `classify_name(name)`, `classify(entry)` — MD class of a file.
- `engine_vote(files)`, `dominant(values)`, `chunk_index(entry)`, `chunk_regularity(chunks)`, `count_bursts(mtimes)`, `files_within(inv, path, max_depth=2)`, `jaccard(a, b)` — building blocks.
- `DirFeatures` — per-directory feature record (field docs in the class docstring).
- `dir_features(inv, path, *, tz_offset_s=0)`, `all_features(inv, *, tz_offset_s=0)` — featurizer.
- `sibling_uniformity(inv, feats, parent_path)` — `(group, uniformity, template_fraction, mode_sig)`.

### `campaign_detector.synth`

- `T0`, `at`, `workday` — re-exported time helpers.
- `TreeBuilder(root="/vol1", *, uid=1000, gid=1000, mtime=T0)` — `dir()`, `file()`, `symlink()`, `copy()`, `hardlink()`, `build()`.
- `CampaignSpec`, `ENGINE_PROFILES`, `md_campaign(tb, root, spec)` — MD campaign layout; returns candidate dir names.
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
  (not representable in the TSV) is skipped as `EINVAL`. Each goes to `on_error` (re-raise there to abort) and
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
| `positive_identity_graduation.kdr_then_abl` | lig029 picked with `known_gap` graduation (XFAIL: identity is invisible to metadata) | lig029 picked via ABL_2013 `cpd03` (same InChIKey, new name) |
| `positive_identity_graduation.kdr_then_abl_copyout` | lig012, lig041 picked (copy-out) | also lig029 (graduation) and lig035 (`notes.txt` mention) |
| `negative_identity.rerun_all` | no picks | no picks: all 46 keys re-run in 2014, coverage cap |
| `negative_identity.in_backup` | no picks | no picks: keys only under `backup/` and `bak/` |
| `negative_identity.earlier` | no picks | no picks: keys only in an earlier pilot campaign and docking list |

The content answers live in `positive_identity_graduation.CONTENT_EXPECTED`
and are checked by `tests/test_content_pipeline.py`. A positive scenario
must declare picks, so `kdr_then_abl` registers its true answer with a
known gap instead of the inventory-only "no pick".

Known limits: the synthetic Desmond profile writes `traj###.dcd`, not real
`<job>_trj/frame*` directories, and the detector finds no campaign in a
real Desmond layout (extension-less frames are not TRAJ for
`features.classify`). The content manifest handles them; the detector does
not yet.
