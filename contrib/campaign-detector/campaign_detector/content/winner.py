"""Winner feature table: one row per candidate for a "what makes a pick" model.

Columns (see :data:`BASE_COLUMNS`): identifiers and the ``label``; identity
(``inchikey14`` and ``scaffold`` allow grouped CV splits); ``meta_*``
features from the inventory (chunk counts, regularity, gaps, trajectory
bytes, wall span, submit rank, restarts, resubmits, replicas); ``content_*``
features from reader metrics aggregated over files *inside* the candidate.

Leakage exclusions, enforced here and asserted by the tests:

* nothing read from a curated directory (written after the selection) and
  nothing from outside the candidate directory;
* no experimental values (``exp_dg`` and every ``exp_*`` metric): they are
  what the human looked at when picking, i.e. a label proxy;
* no detector evidence, score or selection confidence (they *are* the label).

``unknown`` rows are emitted (``label`` = ``unknown``) but should be left out
of training.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

from ..detect import DetectionResult, is_within
from .aggregate import CandidateContent
from .model import CandidateRecord, candidate_key, write_tsv

LEAKAGE_METRIC_PREFIXES: tuple[str, ...] = ("exp_",)
"""Metric key prefixes never used as features (experimental values)."""

EXCLUDED_COLUMNS: frozenset[str] = frozenset({
    "score", "evidence", "n_evidence", "evidence_kinds", "selection_confidence", "exp_dg", "content_exp_dg",
})
"""Column names that must never appear in winner rows."""

BASE_COLUMNS: tuple[str, ...] = (
    "key", "root", "candidate_id", "label", "engine", "era", "unit",
    "inchikey", "inchikey14", "scaffold", "identity_confidence",
)
"""Leading columns, in order; ``meta_*`` then ``content_*`` columns follow, sorted."""


def is_leakage_metric(key: str) -> bool:
    """True for metric keys excluded from features (``exp_dg``, ``exp_*``)."""
    return key.lower().startswith(LEAKAGE_METRIC_PREFIXES)



def _record_counts(rec: CandidateRecord) -> dict[str, object]:
    files = rec.files
    return {
        "meta_traj_bytes": sum(r.size for r in files.get("TRAJ", ())),
        "meta_n_traj_files": len(files.get("TRAJ", ())),
        "meta_n_sched": len(files.get("SCHED", ())),
        "meta_n_restart": len(files.get("RESTART", ())),
        "meta_n_struct": len(files.get("STRUCT", ())),
        "meta_n_replicas": len(rec.replicas),
    }


def winner_rows(result: DetectionResult, aggregates: Mapping[str, CandidateContent], *,
                records: Iterable[CandidateRecord] | None = None,
                include_unknown: bool = True) -> list[dict[str, object]]:
    """Feature rows for every candidate of ``result`` sorted by key; every row has every column."""
    recs = {r.key: r for r in records} if records is not None else {}
    rows: list[dict[str, object]] = []
    for rep in result.campaigns:
        curated = [cd.path for cd in rep.curated_dirs]
        order = sorted(rep.candidates, key=lambda c: (c.features.mtime_min is None, c.features.mtime_min or 0, c.id))
        rank = {c.id: i + 1 for i, c in enumerate(order)}
        for cand in rep.candidates:
            if cand.label == "unknown" and not include_unknown:
                continue
            key = candidate_key(rep.root, cand.id)
            f = cand.features
            content = aggregates.get(key)
            best = content.best if content else None
            rec = recs.get(key)
            row: dict[str, object] = {
                "key": key, "root": rep.root, "candidate_id": cand.id, "label": cand.label, "engine": rep.engine,
                "era": rep.era, "unit": rec.unit if rec else None,
                "inchikey": best.inchikey if best else None, "inchikey14": best.inchikey14 if best else None,
                "scaffold": best.scaffold if best else None, "identity_confidence": best.confidence if best else None,
                "meta_traj_chunk_count": f.traj_chunk_count,
                "meta_traj_chunk_regularity": f.traj_chunk_regularity,
                "meta_traj_series_gap": int(f.traj_series_gap),
                "meta_traj_byte_fraction": f.traj_byte_fraction,
                "meta_md_class_coverage": f.md_class_coverage,
                "meta_n_files": f.n_files,
                "meta_wall_span_s": (f.mtime_max - f.mtime_min) if f.mtime_min is not None
                and f.mtime_max is not None else None,
                "meta_submit_rank": rank[cand.id],
            }
            if rec is not None:
                row.update(_record_counts(rec))
            if content is not None:
                row["content_n_ligands"] = len(content.identities())
                row["content_identity_agree"] = int("identity_agree" in content.flags)
                row["content_multiple_ligands"] = int("multiple_ligands" in content.flags)
                for mkey, value in content.metrics.items():
                    srcs = content.metric_sources.get(mkey, ())
                    if is_leakage_metric(mkey) or not srcs:
                        continue
                    if any(not is_within(s, cand.path) or any(is_within(s, c) for c in curated) for s in srcs):
                        continue
                    row[f"content_{mkey}"] = value
            rows.append(row)
    columns = winner_columns(rows)
    return sorted(({c: r.get(c) for c in columns} for r in rows), key=lambda r: str(r["key"]))


def winner_columns(rows: Iterable[Mapping[str, object]]) -> list[str]:
    """:data:`BASE_COLUMNS` then every other column of ``rows``, sorted."""
    extra = sorted({c for r in rows for c in r} - set(BASE_COLUMNS))
    cols = list(BASE_COLUMNS) + extra
    bad = EXCLUDED_COLUMNS & set(cols)
    if bad:
        raise ValueError(f"leakage columns in winner rows: {sorted(bad)}")
    return cols


def write_winner_tsv(rows: list[dict[str, object]], dst: str | os.PathLike[str]) -> None:
    """Write winner rows as TSV (header row, ``None`` as an empty cell)."""
    columns = winner_columns(rows)
    write_tsv(dst, columns, [[r.get(c) for c in columns] for r in rows])
