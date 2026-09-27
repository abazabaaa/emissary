"""A sha256-keyed cache of reader results.

Each unique file content is read once per ``(reader, reader version)``:
copy-outs, mirrors and boilerplate shared by every candidate collapse to one
read. When the inventory has no sha256 for a file the key falls back to its
metadata (:func:`ref_key`). A hit is re-bound to the path being read, so
provenance (``input_path``, ``source_path``) always names the requesting
file. The cache is a dict; :meth:`ResultCache.save`/:meth:`ResultCache.load`
persist it as five TSVs in a directory (no JSON).
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Iterable

from .model import FileRef, LigandIdentity, Mention, Metric, ReaderResult, read_tsv, write_tsv

RESULT_COLUMNS: tuple[str, ...] = (
    "slot_key", "slot_reader", "slot_version", "toolkit", "toolkit_version", "license_feature", "input_path",
    "input_sha256", "cost", "elapsed_s",
)
LIGAND_COLUMNS: tuple[str, ...] = ("slot_key", "slot_reader", "slot_version") + tuple(
    f.name for f in dataclasses.fields(LigandIdentity))
METRIC_COLUMNS: tuple[str, ...] = ("slot_key", "slot_reader", "slot_version") + tuple(
    f.name for f in dataclasses.fields(Metric))
MENTION_COLUMNS: tuple[str, ...] = ("slot_key", "slot_reader", "slot_version") + tuple(
    f.name for f in dataclasses.fields(Mention))
NOTE_COLUMNS: tuple[str, ...] = ("slot_key", "slot_reader", "slot_version", "kind", "text")

CACHE_FILES: dict[str, tuple[str, ...]] = {
    "cache_results.tsv": RESULT_COLUMNS, "cache_ligands.tsv": LIGAND_COLUMNS,
    "cache_metrics.tsv": METRIC_COLUMNS, "cache_mentions.tsv": MENTION_COLUMNS, "cache_notes.tsv": NOTE_COLUMNS,
}
"""Files written by :meth:`ResultCache.save` and their columns."""

_Slot = tuple[str, str, str]


def ref_key(ref: FileRef) -> str:
    """Cache key of a file: ``sha256:<hex>``, else ``meta:<path>|<size>|<mtime>``."""
    if ref.sha256:
        return f"sha256:{ref.sha256}"
    return f"meta:{ref.path}|{ref.size}|{ref.mtime}"


def result_key(result: ReaderResult) -> str:
    """Cache key of a result read from hashed content (same as :func:`ref_key` of its file).

    A result without ``input_sha256`` has no size/mtime to build the
    metadata key from: ``ValueError`` (pass ``key=ref_key(ref)`` instead).
    """
    if not result.input_sha256:
        raise ValueError(f"result for {result.input_path} has no sha256: pass key=ref_key(ref)")
    return f"sha256:{result.input_sha256}"


def rebind(result: ReaderResult, path: str) -> ReaderResult:
    """A copy of ``result`` whose ``input_path`` and matching ``source_path`` values are ``path``."""
    old = result.input_path

    def fix(p: str) -> str:
        return path if p == old else p

    return dataclasses.replace(
        result, input_path=path,
        ligands=[dataclasses.replace(x, source_path=fix(x.source_path)) for x in result.ligands],
        metrics=[dataclasses.replace(x, source_path=fix(x.source_path)) for x in result.metrics],
        mentions=[dataclasses.replace(x, source_path=fix(x.source_path)) for x in result.mentions],
        flags=list(result.flags), errors=list(result.errors),
    )


class ResultCache:
    """``(key, reader, version) -> ReaderResult`` with hit/miss counters."""

    def __init__(self) -> None:
        self._store: dict[_Slot, ReaderResult] = {}
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._store)

    def get(self, key: str, reader: str, version: str) -> ReaderResult | None:
        """The cached result for ``key`` or ``None`` (counts a hit or a miss)."""
        res = self._store.get((key, reader, version))
        if res is None:
            self.misses += 1
        else:
            self.hits += 1
        return res

    def put(self, result: ReaderResult, *, key: str | None = None) -> None:
        """Store ``result`` under ``key`` (default :func:`result_key`, which needs a sha256)."""
        self._store[(key or result_key(result), result.reader, result.reader_version)] = result

    def items(self) -> list[tuple[_Slot, ReaderResult]]:
        """All entries sorted by slot."""
        return sorted(self._store.items(), key=lambda kv: kv[0])

    def save(self, directory: str | os.PathLike[str]) -> None:
        """Write the cache as the TSVs of :data:`CACHE_FILES` into ``directory`` (created if needed)."""
        os.makedirs(directory, exist_ok=True)
        rows: dict[str, list[tuple[object, ...]]] = {name: [] for name in CACHE_FILES}
        for (key, reader, version), r in self.items():
            slot = (key, reader, version)
            rows["cache_results.tsv"].append(slot + (r.toolkit, r.toolkit_version, r.license_feature, r.input_path,
                                                     r.input_sha256, r.cost, float(r.elapsed_s)))
            rows["cache_ligands.tsv"].extend(slot + dataclasses.astuple(x) for x in r.ligands)
            rows["cache_metrics.tsv"].extend(slot + dataclasses.astuple(x) for x in r.metrics)
            rows["cache_mentions.tsv"].extend(slot + dataclasses.astuple(x) for x in r.mentions)
            rows["cache_notes.tsv"].extend(slot + ("flag", f) for f in r.flags)
            rows["cache_notes.tsv"].extend(slot + ("error", e) for e in r.errors)
        for name, columns in CACHE_FILES.items():
            write_tsv(os.path.join(directory, name), columns, rows[name])

    @classmethod
    def load(cls, directory: str | os.PathLike[str]) -> ResultCache:
        """Read a cache written by :meth:`save`."""
        cache = cls()
        tables = {name: read_tsv(os.path.join(directory, name), cols) for name, cols in CACHE_FILES.items()}
        for row in tables["cache_results.tsv"]:
            slot = _slot(row)
            cache._store[slot] = ReaderResult(
                reader=slot[1], reader_version=slot[2], toolkit=row["toolkit"] or "",
                toolkit_version=row["toolkit_version"] or "", input_path=row["input_path"] or "",
                input_sha256=row["input_sha256"], cost=row["cost"] or "small",
                license_feature=row["license_feature"], elapsed_s=float(row["elapsed_s"] or 0.0),
            )
        for row in tables["cache_ligands.tsv"]:
            cache._store[_slot(row)].ligands.append(LigandIdentity(**_fields(row, LigandIdentity)))
        for row in tables["cache_metrics.tsv"]:
            vals = _fields(row, Metric)
            vals["value"] = float(vals["value"] or "nan")
            cache._store[_slot(row)].metrics.append(Metric(**vals))
        for row in tables["cache_mentions.tsv"]:
            cache._store[_slot(row)].mentions.append(Mention(**_fields(row, Mention)))
        for row in tables["cache_notes.tsv"]:
            target = cache._store[_slot(row)]
            (target.flags if row["kind"] == "flag" else target.errors).append(row["text"] or "")
        return cache

    def update(self, results: Iterable[tuple[str, ReaderResult]]) -> None:
        """Store several ``(key, result)`` pairs."""
        for key, r in results:
            self.put(r, key=key)


_OPTIONAL = {"name", "inchikey", "inchikey14", "smiles", "scaffold"}


def _slot(row: dict[str, str | None]) -> _Slot:
    return (row["slot_key"] or "", row["slot_reader"] or "", row["slot_version"] or "")


def _fields(row: dict[str, str | None], klass: type) -> dict[str, object]:
    out: dict[str, object] = {}
    for f in dataclasses.fields(klass):
        v = row[f.name]
        out[f.name] = v if (v is not None or f.name in _OPTIONAL) else ""
    return out
