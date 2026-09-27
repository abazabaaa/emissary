"""Two-pass detection with content readers.

Pass 1 runs the inventory-only detector to find campaigns and candidates.
Then every candidate's files (:func:`~.manifest.candidate_records`) and the
*loose* files outside every candidate (structures, result tables and human
documents: classes in :data:`LOOSE_CLASSES`) go through the reader registry;
candidate results are aggregated (:mod:`.aggregate`), and a
:class:`~.graduation.GraduationIndex` and a :class:`~.mentions.MentionIndex`
are built. Pass 2 reruns the detector with both indexes as ``Hooks``.
Campaign roots and candidates are the same in both passes (hooks only add
evidence), so the records built in pass 1 stay valid.
"""

from __future__ import annotations

import os
import posixpath
from dataclasses import dataclass

from ..detect import DetectionResult, Hooks, Params, detect
from ..inventory import Inventory
from .aggregate import CandidateContent, aggregate_all
from .cache import ResultCache
from .fake import fake_registry
from .graduation import GraduationIndex
from .manifest import candidate_records, classify_content
from .mentions import MentionIndex
from .model import CandidateRecord, FileRef, ReaderResult
from .registry import ReaderRegistry

LOOSE_CLASSES: frozenset[str] = frozenset({"STRUCT", "RESULT", "DERIVED"})
"""Content classes read outside candidates: identity sources, registry exports, notes."""


@dataclass
class ContentRun:
    """Everything a content-aware detection produced."""

    result: DetectionResult
    first_pass: DetectionResult
    records: list[CandidateRecord]
    results: dict[str, list[ReaderResult]]
    loose: list[ReaderResult]
    contents: dict[str, CandidateContent]
    graduation: GraduationIndex
    mentions: MentionIndex
    cache: ResultCache


def loose_refs(inv: Inventory, records: list[CandidateRecord]) -> list[FileRef]:
    """Files outside every candidate directory whose content class is in :data:`LOOSE_CLASSES`."""
    cand_paths = {r.path for r in records}
    out = []
    for e in inv.files():
        p = e.parent
        inside = False
        while p is not None and p != "/":
            if p in cand_paths:
                inside = True
                break
            p = posixpath.dirname(p)
        if inside:
            continue
        cls, fmt = classify_content(e)
        if cls in LOOSE_CLASSES:
            out.append(FileRef(e.path, e.sha256, e.size, e.mtime, cls, fmt))
    return out


def run_content(inv: Inventory, registry: ReaderRegistry, *, cache: ResultCache | None = None,
                params: Params | None = None, max_cost: str = "small", mention_weight: float = 0.7,
                strong: float = 1.0, weak: float = 0.5) -> ContentRun:
    """Run both passes and keep every intermediate (records, results, contents, indexes)."""
    cache = cache if cache is not None else ResultCache()
    first = detect(inv, params=params)
    records = candidate_records(inv, first)
    results = {rec.key: registry.read_candidate(rec, max_cost=max_cost, cache=cache) for rec in records}
    loose = [res for ref in loose_refs(inv, records)
             for res in registry.read_file(ref, None, max_cost=max_cost, cache=cache)]
    contents = aggregate_all(records, results)
    grad = GraduationIndex.build(inv, first, contents, loose)
    ments = MentionIndex.from_results([r for rs in results.values() for r in rs] + loose, contents)
    hooks = Hooks(text_mentions=ments.hook(weight=mention_weight), graduation=grad.hook(strong=strong, weak=weak))
    second = detect(inv, params=params, hooks=hooks)
    return ContentRun(result=second, first_pass=first, records=records, results=results, loose=loose,
                      contents=contents, graduation=grad, mentions=ments, cache=cache)


def detect_with_content(inv: Inventory, content_dir: str | os.PathLike[str] | None, *,
                        params: Params | None = None, registry: ReaderRegistry | None = None,
                        cache: ResultCache | None = None, max_cost: str = "small") -> DetectionResult:
    """Detect with content facts; by default a :class:`~.fake.FakeReader` over ``content_dir``.

    With no sidecar facts (or ``content_dir=None`` and no registry) the
    result equals ``detect(inv, params=params)``.
    """
    reg = registry if registry is not None else fake_registry(content_dir)
    return run_content(inv, reg, cache=cache, params=params, max_cost=max_cost).result
