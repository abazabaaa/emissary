"""Content readers: a vendor-neutral seam for facts read from file contents.

The detector itself only reads inventory metadata. This package adds a
second, optional pass that reads *contents* through per-file readers
(OpenEye, Schrodinger or open-source services in production; the sidecar
:class:`~campaign_detector.content.fake.FakeReader` in tests) and feeds the
facts back in through :class:`~campaign_detector.detect.Hooks`:

* :mod:`.model` -- the stdlib-only schema (``FileRef``, ``CandidateRecord``,
  ``LigandIdentity``, ``Metric``, ``Mention``, ``ReaderResult``, ``Reader``);
* :mod:`.manifest` -- content file classes and per-candidate file manifests;
* :mod:`.registry`, :mod:`.cache` -- reader dispatch by (engine, format) and a
  sha256-keyed result cache;
* :mod:`.sidecar`, :mod:`.fake` -- sidecar TSVs for synthetic scenarios and
  the reader that serves them;
* :mod:`.aggregate`, :mod:`.graduation`, :mod:`.mentions`, :mod:`.pipeline`,
  :mod:`.winner` -- per-candidate facts, the two evidence hooks, the
  two-pass ``detect_with_content`` and the winner feature table.

Only the schema is re-exported here so that importing this package from a
vendor interpreter pulls in nothing but the standard library.
"""

from __future__ import annotations

from .model import (
    CONFIDENCES, COSTS, FILE_CLASSES, LIGAND_ROLES, MENTION_KINDS, ROLES, UNITS, CandidateRecord, Cost, FileRef,
    LigandIdentity, Mention, Metric, Reader, ReaderResult, candidate_key,
)

__all__ = [
    "CONFIDENCES", "COSTS", "FILE_CLASSES", "LIGAND_ROLES", "MENTION_KINDS", "ROLES", "UNITS", "CandidateRecord",
    "Cost", "FileRef", "LigandIdentity", "Mention", "Metric", "Reader", "ReaderResult", "candidate_key",
]
