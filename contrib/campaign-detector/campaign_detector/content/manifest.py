"""Content file classes and per-candidate file manifests.

:func:`classify_content` is a separate, richer table than the detector's
``features.classify_name``: it understands double suffixes (``x.oeb.gz``,
``x.sdf.gz``), Maestro's ``.maegz``, name patterns (``*_pv.maegz`` Glide
pose-viewer files, ``*-out.cms`` Desmond outputs, ``*_out.fmp`` FEP+ maps)
and Desmond ``<job>_trj/`` directories of extension-less ``frame*`` files.
The detector's ``MD_CLASSES`` are deliberately left alone: they feed the
directory signatures that find campaigns.

:func:`candidate_records` walks every candidate of a detection result at any
depth (FEP lambda and replica levels can be deeper than two) and returns one
:class:`~campaign_detector.content.model.CandidateRecord` per candidate.
"""

from __future__ import annotations

import posixpath
import re

from ..detect import DetectionResult
from ..features import REPLICA_WORDS, SCHED_RE, classify_name, tokens
from ..inventory import Entry, Inventory
from .model import CandidateRecord, FileRef

TRJ_DIR_SUFFIX = "_trj"
"""Name suffix of a Desmond trajectory directory (``md_trj/`` holding ``frame*`` and ``clickme.dtr``)."""

COMPRESSION_SUFFIXES: tuple[str, ...] = (".gz", ".bz2", ".xz")
"""Generic compression suffixes stripped before classification (``lig.oeb.gz`` is an ``oeb``)."""

NAME_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"_pv\.mae(gz)?$"), "STRUCT", "glide.pv"),
    (re.compile(r"_lib\.mae(gz)?$"), "STRUCT", "glide.lib"),
    (re.compile(r"-out\.cms$"), "TOPO", "desmond.cms"),
    (re.compile(r"-in\.cms$"), "TOPO", "desmond.cms"),
    (re.compile(r"-out\.cfg$"), "INPUT", "desmond.cfg"),
    (re.compile(r"_out\.fmp$"), "RESULT", "fep.fmp"),
    (re.compile(r"^multisim\.log$"), "LOG", "desmond.multisim_log"),
    (re.compile(r"^(rmsd|rmsf)[\w.-]*\.(dat|xvg)$"), "RESULT", "analysis.series"),
)
"""Whole-name patterns checked (on the lower-cased name) before suffixes."""

SUFFIXES: dict[str, tuple[str, str]] = {
    # structures and identity sources
    ".maegz": ("STRUCT", "mae"), ".mae": ("STRUCT", "mae"), ".oeb": ("STRUCT", "oeb"), ".oez": ("STRUCT", "oez"),
    ".oedu": ("STRUCT", "oedu"), ".sdf": ("STRUCT", "sdf"), ".sd": ("STRUCT", "sdf"), ".mol2": ("STRUCT", "mol2"),
    ".mol": ("STRUCT", "mol"), ".pdb": ("STRUCT", "pdb"), ".smi": ("STRUCT", "smi"), ".cif": ("STRUCT", "cif"),
    # Schrodinger / Desmond / FEP+
    ".cms": ("TOPO", "desmond.cms"), ".cfg": ("INPUT", "desmond.cfg"), ".msj": ("INPUT", "desmond.msj"),
    ".dtr": ("TRAJ", "desmond.dtr"), ".ene": ("LOG", "desmond.ene"), ".eaf": ("RESULT", "desmond.eaf"),
    ".chk": ("RESTART", "desmond.chk"), ".fmp": ("RESULT", "fep.fmp"), ".fmpdb": ("TRAJ", "fep.fmpdb"),
    ".prj": ("RESULT", "maestro.prj"), ".prjzip": ("RESULT", "maestro.prjzip"),
    # AMBER
    ".prmtop": ("TOPO", "amber.prmtop"), ".parm7": ("TOPO", "amber.prmtop"), ".frcmod": ("TOPO", "amber.frcmod"),
    ".lib": ("TOPO", "amber.lib"), ".nc": ("TRAJ", "amber.nc"), ".mdcrd": ("TRAJ", "amber.mdcrd"),
    ".rst7": ("RESTART", "amber.rst7"), ".ncrst": ("RESTART", "amber.rst7"),
    ".mdout": ("LOG", "amber.mdout"),
    # GROMACS
    ".top": ("TOPO", "gromacs.top"), ".itp": ("TOPO", "gromacs.itp"), ".gro": ("TOPO", "gromacs.gro"),
    ".tpr": ("TOPO", "gromacs.tpr"), ".mdp": ("INPUT", "gromacs.mdp"), ".xtc": ("TRAJ", "gromacs.xtc"),
    ".trr": ("TRAJ", "gromacs.trr"), ".edr": ("LOG", "gromacs.edr"), ".cpt": ("RESTART", "gromacs.cpt"),
    # NAMD / CHARMM
    ".psf": ("TOPO", "namd.psf"), ".str": ("TOPO", "charmm.str"), ".coor": ("RESTART", "namd.coor"),
    ".vel": ("RESTART", "namd.vel"), ".xsc": ("RESTART", "namd.xsc"), ".namd": ("INPUT", "namd.conf"),
    ".conf": ("INPUT", "namd.conf"), ".inp": ("INPUT", "namd.conf"),
    # engine-ambiguous
    ".dcd": ("TRAJ", "dcd"), ".in": ("INPUT", "mdin"), ".out": ("LOG", "log"), ".log": ("LOG", "log"),
    ".err": ("LOG", "log"), ".gjf": ("INPUT", "gaussian.gjf"),
    # results and human artifacts
    ".csv": ("RESULT", "csv"), ".tsv": ("RESULT", "tsv"), ".xlsx": ("DERIVED", "xlsx"), ".xls": ("DERIVED", "xls"),
    ".pptx": ("DERIVED", "pptx"), ".docx": ("DERIVED", "docx"), ".ipynb": ("DERIVED", "ipynb"),
    ".png": ("DERIVED", "image"), ".jpg": ("DERIVED", "image"), ".jpeg": ("DERIVED", "image"),
    ".svg": ("DERIVED", "image"), ".pdf": ("DERIVED", "pdf"), ".txt": ("DERIVED", "text"),
    ".md": ("DERIVED", "text"), ".rst": ("DERIVED", "text"), ".pse": ("DERIVED", "pymol.pse"),
    ".vmd": ("DERIVED", "vmd"), ".tcl": ("DERIVED", "vmd"),
}
"""Last-suffix table (lower case) applied after :data:`NAME_PATTERNS` and compression stripping."""

ENGINE_FMTS: dict[tuple[str, str], str] = {
    ("amber", "log"): "amber.mdout", ("amber", "mdin"): "amber.mdin",
    ("gromacs", "log"): "gromacs.log",
    ("namd", "log"): "namd.log", ("namd", "dcd"): "namd.dcd",
    ("desmond", "log"): "desmond.log", ("desmond", "dcd"): "desmond.dcd",
}
"""Refinement of engine-ambiguous formats by the campaign's engine."""

ENGINE_SUFFIXES: dict[tuple[str, str], tuple[str, str]] = {
    ("amber", ".rst"): ("RESTART", "amber.rst7"),
}
"""Suffixes whose class depends on the engine (``.rst``: Amber restart in an Amber run, else reStructuredText)."""


def _split_compression(name: str) -> tuple[str, str]:
    for suffix in COMPRESSION_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)], suffix
    return name, ""


def classify_content_name(name: str, *, is_dir: bool = False, parent_name: str = "",
                          engine: str | None = None) -> tuple[str, str]:
    """``(file_class, fmt)`` of a file or directory name.

    A directory is ``("TRAJ", "desmond.trj_dir")`` when its name ends in
    ``_trj`` and ``("OTHER", "dir")`` otherwise; a file directly inside a
    ``_trj`` directory is ``("TRAJ", "desmond.trj_frame")``. Scheduler
    outputs are ``SCHED`` (``features.SCHED_RE``). Unknown names fall back
    to the detector's class with ``fmt`` = the bare suffix (or ``unknown``).
    """
    lower = name.lower()
    if is_dir:
        return ("TRAJ", "desmond.trj_dir") if lower.endswith(TRJ_DIR_SUFFIX) else ("OTHER", "dir")
    if parent_name.lower().endswith(TRJ_DIR_SUFFIX):
        return "TRAJ", "desmond.trj_frame"
    if SCHED_RE.search(lower):
        return "SCHED", "sched.pbs" if not lower.startswith("slurm-") else "sched.slurm"
    for pattern, cls, fmt in NAME_PATTERNS:
        if pattern.search(lower):
            return cls, fmt
    inner, _ = _split_compression(lower)
    if inner != lower:
        for pattern, cls, fmt in NAME_PATTERNS:
            if pattern.search(inner):
                return cls, fmt
    ext = posixpath.splitext(inner)[1]
    if (engine or "", ext) in ENGINE_SUFFIXES:
        return ENGINE_SUFFIXES[(engine or "", ext)]
    if ext in SUFFIXES:
        cls, fmt = SUFFIXES[ext]
        return cls, ENGINE_FMTS.get((engine or "", fmt), fmt)
    return classify_name(name), (ext[1:] if ext else "unknown")


def classify_content(entry: Entry, *, engine: str | None = None) -> tuple[str, str]:
    """``(file_class, fmt)`` of an inventory entry (see :func:`classify_content_name`)."""
    parent = posixpath.basename(entry.parent) if entry.parent else ""
    return classify_content_name(entry.name, is_dir=entry.kind == "d", parent_name=parent, engine=engine)


_EDGE_RE = re.compile(r"(_to_|-to-|~|->)")
_ID_RUN_RE = re.compile(r"([a-z]+)\d+")
_NOT_EDGE_PREFIXES = frozenset(REPLICA_WORDS | {"v", "ver", "run", "try"})
_LEG_WORDS = frozenset({"complex", "solvent", "vacuum", "leg"})


def candidate_unit(candidate_id: str) -> str:
    """What a candidate directory name stands for: ``leg``, ``edge``, ``ligand`` or ``unknown``.

    ``complex``/``solvent``/``vacuum``/``leg`` tokens mean a leg; ``a_to_b``,
    ``a~b``, ``a->b`` or two id runs with the same letters (``lig01_lig07``)
    mean an RBFE edge; any other name with a digit run (``cpd12_v2``,
    ``kdr2_lig05``) is one ligand.
    """
    lower = candidate_id.lower()
    if set(tokens(candidate_id)) & _LEG_WORDS:
        return "leg"
    prefixes = [p for p in _ID_RUN_RE.findall(lower) if p not in _NOT_EDGE_PREFIXES]
    if _EDGE_RE.search(lower) or any(prefixes.count(p) >= 2 for p in prefixes):
        return "edge"
    if any(ch.isdigit() for ch in lower):
        return "ligand"
    return "unknown"


def _is_replica_dir(name: str) -> bool:
    return bool(set(tokens(name)) & REPLICA_WORDS)


def _companions(ref: FileRef, topos_by_dir: dict[str, list[str]], cand_topos: list[str]) -> tuple[str, ...]:
    """Topology companions of a trajectory: same directory first, else the candidate's."""
    d = posixpath.dirname(ref.path)
    if ref.fmt == "desmond.trj_dir":
        job = posixpath.basename(ref.path)[: -len(TRJ_DIR_SUFFIX)]
        preferred = [p for p in topos_by_dir.get(d, []) if posixpath.basename(p) == f"{job}-out.cms"]
        if preferred:
            return tuple(preferred)
    local = topos_by_dir.get(d)
    return tuple(local if local else cand_topos)


def _trj_ref(inv: Inventory, entry: Entry) -> FileRef:
    members = [e for e in inv.subtree(entry.path) if e.kind == "f"]
    return FileRef(
        path=entry.path, sha256=None, size=sum(e.size for e in members),
        mtime=max((e.mtime for e in members), default=entry.mtime),
        file_class="TRAJ", fmt="desmond.trj_dir",
    )


def record_files(inv: Inventory, path: str, *, engine: str | None = None
                 ) -> tuple[dict[str, tuple[FileRef, ...]], tuple[str, ...]]:
    """``(files by class, replica sub-dirs)`` of the directory ``path`` at any depth.

    Regular files become one ref each; a ``*_trj`` directory becomes one TRAJ
    ref whose size is the sum of its files and whose mtime is the newest
    (its members are not listed). Symlinks are skipped: they are pointers,
    not content. Trajectories get their topologies as ``companions``.
    """
    raw: list[FileRef] = []
    replicas: list[str] = []
    stack = list(reversed(inv.children(path)))
    while stack:
        e = stack.pop()
        if e.kind == "d":
            if e.name.lower().endswith(TRJ_DIR_SUFFIX):
                raw.append(_trj_ref(inv, e))
                continue
            if _is_replica_dir(e.name):
                replicas.append(posixpath.relpath(e.path, path))
            stack.extend(reversed(inv.children(e.path)))
        elif e.kind == "f":
            cls, fmt = classify_content(e, engine=engine)
            raw.append(FileRef(e.path, e.sha256, e.size, e.mtime, cls, fmt))
    topos = sorted(r.path for r in raw if r.file_class == "TOPO")
    topos_by_dir: dict[str, list[str]] = {}
    for t in topos:
        topos_by_dir.setdefault(posixpath.dirname(t), []).append(t)
    cand_topos = topos_by_dir.get(path, topos)
    by_class: dict[str, list[FileRef]] = {}
    for r in raw:
        if r.file_class == "TRAJ":
            r = FileRef(r.path, r.sha256, r.size, r.mtime, r.file_class, r.fmt,
                        _companions(r, topos_by_dir, cand_topos))
        by_class.setdefault(r.file_class, []).append(r)
    files = {cls: tuple(sorted(refs, key=lambda r: r.path)) for cls, refs in sorted(by_class.items())}
    return files, tuple(sorted(replicas))


def candidate_records(inv: Inventory, result: DetectionResult) -> list[CandidateRecord]:
    """One :class:`CandidateRecord` per candidate of every campaign, sorted by key."""
    out: list[CandidateRecord] = []
    for rep in result.campaigns:
        for cand in rep.candidates:
            files, replicas = record_files(inv, cand.path, engine=rep.engine)
            out.append(CandidateRecord(
                root=rep.root, candidate_id=cand.id, path=cand.path, engine=rep.engine, era=rep.era,
                t_start=rep.t_start, t_end=rep.t_end, label=cand.label, unit=candidate_unit(cand.id),
                replicas=replicas, files=files,
            ))
    return sorted(out, key=lambda r: r.key)
