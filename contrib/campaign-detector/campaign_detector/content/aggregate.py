"""Per-candidate aggregation of reader results.

Only results for files inside the candidate directory count: content in
curated directories is written *after* selection, so it may become evidence
but never a feature. Identities are grouped by InChIKey; the best one is the
ligand-role key with the highest confidence, then the most independent
source files, then the smallest key (deterministic). Metrics with several
values (per-chunk logs) are averaged; ``metric_sources`` keeps provenance.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field

from ..detect import is_within
from .model import (
    LIGAND_ROLES, CandidateRecord, LigandIdentity, ReaderResult, confidence_rank, connectivity_block,
)



@dataclass
class CandidateContent:
    """Content facts of one candidate.

    ``ligands`` are distinct ``(inchikey, source_path, role)`` identities;
    ``best`` the chosen ligand identity. ``flags``: ``identity_agree`` (two
    or more files give the best key), ``multiple_ligands`` (ligand-role
    identities with different connectivity), ``no_identity``, plus every
    reader flag. ``metrics`` maps key -> mean value.
    """

    key: str
    root: str
    candidate_id: str
    path: str
    ligands: list[LigandIdentity] = field(default_factory=list)
    best: LigandIdentity | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    metric_sources: dict[str, tuple[str, ...]] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    n_results: int = 0

    def identities(self) -> list[LigandIdentity]:
        """One ligand-role identity per distinct InChIKey (the most confident source of each)."""
        best: dict[str, LigandIdentity] = {}
        for lig in self.ligands:
            if lig.role not in LIGAND_ROLES or not lig.inchikey:
                continue
            cur = best.get(lig.inchikey)
            if cur is None or (-confidence_rank(lig.confidence), lig.source_path) < \
                    (-confidence_rank(cur.confidence), cur.source_path):
                best[lig.inchikey] = lig
        return [best[k] for k in sorted(best)]


def aggregate(rec: CandidateRecord, results: Iterable[ReaderResult]) -> CandidateContent:
    """Aggregate the results for files of ``rec`` (results for other paths are ignored)."""
    out = CandidateContent(key=rec.key, root=rec.root, candidate_id=rec.candidate_id, path=rec.path)
    values: dict[str, list[float]] = {}
    sources: dict[str, set[str]] = {}
    seen: set[tuple[str | None, str, str]] = set()
    for res in results:
        if not is_within(res.input_path, rec.path):
            continue
        out.n_results += 1
        out.flags.update(res.flags)
        out.errors.extend(f"{res.reader}: {res.input_path}: {e}" for e in res.errors)
        for lig in res.ligands:
            if is_within(lig.source_path, rec.path) and (lig.inchikey, lig.source_path, lig.role) not in seen:
                seen.add((lig.inchikey, lig.source_path, lig.role))
                out.ligands.append(lig)
        for m in res.metrics:
            if is_within(m.source_path, rec.path):
                values.setdefault(m.key, []).append(m.value)
                sources.setdefault(m.key, set()).add(m.source_path)
    out.ligands.sort(key=lambda x: (x.inchikey or "", x.source_path, x.role, x.source_record))
    out.metrics = {k: statistics.fmean(v) for k, v in sorted(values.items())}
    out.metric_sources = {k: tuple(sorted(sources[k])) for k in sorted(sources)}

    support: dict[str, set[str]] = {}
    for lig in out.ligands:
        if lig.role in LIGAND_ROLES and lig.inchikey:
            support.setdefault(lig.inchikey, set()).add(lig.source_path)
    ids = {i.inchikey: i for i in out.identities()}
    if not ids:
        out.flags.add("no_identity")
        return out
    top = min(ids, key=lambda k: (-confidence_rank(ids[k].confidence), -len(support[k]), k))
    out.best = ids[top]
    if len(support[top]) >= 2:
        out.flags.add("identity_agree")
    if len({i.inchikey14 or connectivity_block(i.inchikey) for i in ids.values()}) > 1:
        out.flags.add("multiple_ligands")
    return out


def aggregate_all(records: Iterable[CandidateRecord],
                  results: dict[str, list[ReaderResult]]) -> dict[str, CandidateContent]:
    """:func:`aggregate` for every record; ``results`` maps record key -> its results."""
    return {rec.key: aggregate(rec, results.get(rec.key, [])) for rec in records}
