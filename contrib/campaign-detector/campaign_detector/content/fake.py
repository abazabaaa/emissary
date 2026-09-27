"""A reader that serves sidecar TSVs, standing in for licensed toolkits.

:class:`FakeReader` implements the :class:`~campaign_detector.content.model.Reader`
protocol over the sidecars written by :func:`campaign_detector.content.sidecar.write`.
It accepts a file when the sidecar declares facts for its path (and, when
both sides know a sha256, the hashes agree: a stale sidecar is refused) or
for its sha256 (a byte copy carries the same facts). Results are
deterministic: rows come back in sidecar order and ``elapsed_s`` is 0.
"""

from __future__ import annotations

import os

from . import sidecar
from .model import FileRef, LigandIdentity, Mention, Metric, ReaderResult
from .registry import ANY_FORMAT, ReaderRegistry


class FakeReader:
    """Serve :class:`~campaign_detector.content.model.ReaderResult` s from a sidecar directory."""

    name = "fake-sidecar"
    version = "1"
    cost = "small"

    def __init__(self, content_dir: str | os.PathLike[str] | None = None, *,
                 data: sidecar.SidecarData | None = None) -> None:
        if data is None:
            data = sidecar.read(content_dir) if content_dir is not None else sidecar.SidecarData([], [], [])
        self.data = data
        self.reads = 0

    def _rows(self, ref: FileRef) -> dict[str, list[sidecar.Row]] | None:
        rows = self.data.by_path.get(ref.path)
        if rows is not None:
            recorded = self.data.sha_of(ref.path)
            if recorded is None or ref.sha256 is None or recorded == ref.sha256:
                return rows
        if ref.sha256:
            return self.data.by_sha.get(ref.sha256)
        return None

    def can_read(self, ref: FileRef) -> bool:
        """True if the sidecar declares facts for this file's path or content."""
        return self._rows(ref) is not None

    def read(self, ref: FileRef) -> ReaderResult:
        """The declared facts of ``ref``, with ``ref.path`` as their provenance."""
        rows = self._rows(ref)
        if rows is None:
            raise KeyError(f"no sidecar facts for {ref.path}")
        self.reads += 1
        ligands = [LigandIdentity(
            role=r["role"] or "ligand", name=r["name"], inchikey=r["inchikey"], inchikey14=r["inchikey14"],
            smiles=r["smiles"], scaffold=r["scaffold"], canon=r["canon"] or sidecar.FAKE_CANON,
            stereo=r["stereo"] or "none", confidence=r["confidence"] or "low", source_path=ref.path,
            source_record=r["record"] or "",
        ) for r in rows.get("ligands", [])]
        metrics = [Metric(key=r["key"] or "", value=float(r["value"] or "nan"), unit=r["unit"] or "",
                          source_path=ref.path, cost=r["cost"] or self.cost, scope=r["scope"] or "file")
                   for r in rows.get("metrics", [])]
        mentions = [Mention(token=r["token"] or "", kind=r["kind"] or "candidate_id", source_path=ref.path)
                    for r in rows.get("mentions", [])]
        return ReaderResult(reader=self.name, reader_version=self.version, toolkit="sidecar",
                            toolkit_version=sidecar.FAKE_CANON, input_path=ref.path, input_sha256=ref.sha256,
                            cost=self.cost, ligands=ligands, metrics=metrics, mentions=mentions)


def fake_registry(content_dir: str | os.PathLike[str] | None) -> ReaderRegistry:
    """A registry with one :class:`FakeReader` for every format."""
    reg = ReaderRegistry()
    reg.register(FakeReader(content_dir), fmts=[ANY_FORMAT])
    return reg
