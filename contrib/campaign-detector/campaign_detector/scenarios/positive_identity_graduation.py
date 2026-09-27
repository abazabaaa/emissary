"""Identity graduation: a KDR FEP ligand re-simulated, renamed, in a later campaign.

The KDR 2011 Amber FEP campaign (same shape as ``positive_amber_basic.kdr_fep``:
46 of 48 ligands, 20 x 6 h chunks) now also holds each ligand's antechamber
``lig0NN.mol2`` and a per-run ``ti_summary.csv``. The analyst's ``analysis/``
directory is curated but, in ``kdr_then_abl``, holds no copy, link or plot of
any run. Two years later, uid 2005 runs an 8-compound ABL selectivity
campaign on another volume (``/vol5/projects/ABL_2013/md/cpd01..cpd08``);
``cpd03`` is KDR's lig029 (compound ``KDR-0877``) under a new name. The only
trace of the pick is that InChIKey, which only a content reader sees.

**Two answers per scenario.** The registry expectation is what the
inventory-only ``detect`` must produce; :data:`CONTENT_EXPECTED` is what
``campaign_detector.content.pipeline.detect_with_content`` must produce with
the sidecars declared in :data:`CONTENT` (``tests/test_content_pipeline.py``
checks it).

* ``kdr_then_abl``: the true answer is "lig029 picked". A positive scenario
  must declare picks, so the registry carries that true answer with a
  ``graduation`` known gap (inventory-only detect cannot see identity: XFAIL);
  the content answer is the same and passes.
* ``kdr_then_abl_copyout``: the analyst also copies ``prod010.nc`` of lig012
  and lig041 into ``analysis/`` and ``notes.txt`` mentions lig035. The
  registry carries the honest inventory-only answer (012, 041 picked); the
  content answer adds lig029 (graduation) and lig035 (text mention).

The helpers here (:func:`ligand_campaign`, :func:`kdr_campaign`,
:func:`merge`) are reused by ``negative_identity``.
"""

from __future__ import annotations

import posixpath
from collections.abc import Callable

from ..content.sidecar import SidecarBuilder
from ..features import id_token
from ..inventory import Inventory
from ..synth import (
    AnalysisSpec, CampaignSpec, ExpectedOutcome, TreeBuilder, at, human_analysis, md_campaign, pick_by_copy, workday,
)
from . import register

WEEK = -495
"""Weeks from ``T0`` to Monday 2011-03-14 (KDR FEP submission)."""
WD = 5 * WEEK
"""Workday index of that Monday."""

KDR_ROOT = "/vol3/projects/KDR_2011/fep"
KDR_SPEC = CampaignSpec(
    engine="amber", n_candidates=48, candidate_fmt="run_lig{:03d}", n_chunks=20, chunk_interval_s=6 * 3600,
    chunk_size=1_200_000_000, uid=2001, skip=frozenset({17, 33}), start=at(7 * WEEK, 3),
)
"""The KDR campaign (as in ``positive_amber_basic``)."""

ANALYST = 3002
"""uid of the colleague who curates the KDR results."""

ABL_WEEK = WEEK + 106
"""Monday 2013-03-25: the ABL selectivity campaign."""
ABL_ROOT = "/vol5/projects/ABL_2013/md"
ABL_SPEC = CampaignSpec(
    engine="amber", n_candidates=8, candidate_fmt="cpd{:02d}", n_chunks=10, chunk_interval_s=6 * 3600,
    chunk_size=900_000_000, uid=2005, start=at(7 * ABL_WEEK, 2),
)
"""The later campaign on another volume."""

ABL_FROM_KDR: dict[int, int] = {3: 29}
"""ABL candidate index -> KDR ligand index it re-runs (cpd03 is lig029, compound KDR-0877)."""

_R = ("C", "CC", "OC", "N", "F", "Cl", "C#N", "C(F)(F)F", "OCC", "N(C)C")


def kdr_smiles(i: int) -> str:
    """Placeholder SMILES of KDR ligand ``i`` (distinct for i < 100)."""
    return f"O=C(Nc1ccc({_R[i % 10]})cc1)c1ccnc(N{_R[(i // 10) % 10]})c1"


def other_smiles(series: str, j: int) -> str:
    """Placeholder SMILES of compound ``j`` of an unrelated ``series`` (never a KDR ligand)."""
    return f"c1cnc2[nH]cc({_R[j % 10]})c2c1C(=O)N{_R[(j // 10) % 10]}.{series}"


def kdr_compound(i: int) -> str:
    """Corporate id of KDR ligand ``i`` (lig029 -> ``KDR-0877``)."""
    return f"KDR-{848 + i:04d}"


def spec_indices(spec: CampaignSpec) -> list[int]:
    """Candidate indices that exist (``1..n_candidates`` minus ``skip``), in candidate order."""
    return [i for i in range(1, spec.n_candidates + 1) if i not in spec.skip]


def ligand_campaign(tb: TreeBuilder, sb: SidecarBuilder, root: str, spec: CampaignSpec,
                    smiles_of: Callable[[int], str], *, name_of: Callable[[int], str | None] = lambda i: None,
                    metrics: bool = False) -> list[str]:
    """An MD campaign whose runs each hold ``<id>.mol2`` with a declared ligand identity.

    ``smiles_of(i)``/``name_of(i)`` give candidate ``i``'s molecule and
    compound id. With ``metrics`` each run also gets ``ti_summary.csv``
    (``dg_pred``, ``dg_unc`` and the leakage column ``exp_dg``) and
    run-log metrics (``sim_time_ns``, ``ns_per_day``) on its last chunk log.
    """
    names = md_campaign(tb, root, spec)
    last_chunk = f"prod{spec.n_chunks:03d}.out"
    for c, (i, cid) in enumerate(zip(spec_indices(spec), names, strict=True)):
        run = posixpath.join(root, cid)
        t0 = spec.start + c * spec.stagger_s
        mol2 = tb.file(posixpath.join(run, f"{id_token(cid) or cid}.mol2"), size=6_000, mtime=t0 - 3600,
                       uid=spec.uid)
        sb.ligand(mol2, smiles_of(i), name=name_of(i), confidence="high", scaffold="c1ccncc1")
        if metrics:
            done = t0 + spec.n_chunks * spec.chunk_interval_s
            csv = tb.file(posixpath.join(run, "ti_summary.csv"), size=1_200, mtime=done, uid=spec.uid)
            sb.metric(csv, "dg_pred", round(-7.0 - ((i * 37) % 41) / 10, 2), "kcal/mol")
            sb.metric(csv, "dg_unc", round(0.15 + (i % 5) * 0.05, 2), "kcal/mol")
            sb.metric(csv, "exp_dg", round(-6.5 - ((i * 13) % 37) / 10, 2), "kcal/mol", scope="node")
            log = posixpath.join(run, last_chunk)
            sb.metric(log, "sim_time_ns", spec.n_chunks * 2.5, "ns")
            sb.metric(log, "ns_per_day", 8.0 + (i % 7), "ns/day")
    return names


def kdr_campaign(tb: TreeBuilder, sb: SidecarBuilder) -> str:
    """The KDR 2011 campaign with identities, metrics and a curated ``analysis/``; returns its path."""
    ligand_campaign(tb, sb, KDR_ROOT, KDR_SPEC, kdr_smiles, name_of=kdr_compound, metrics=True)
    tb.file(posixpath.join(KDR_ROOT, "submit_all.sh"), size=1_800, mtime=KDR_SPEC.start - 600, uid=KDR_SPEC.uid)
    return human_analysis(tb, KDR_ROOT, AnalysisSpec(
        uid=ANALYST, first_workday=WD + 15, bursts=3,
        files=("dG_summary_v3.xlsx", "notes.txt", "KDR_FEP_topHits_forMedChem.pptx", "README.md"),
    ))


def abl_smiles(j: int) -> str:
    """ABL compound ``j``: a KDR ligand for :data:`ABL_FROM_KDR` entries, else its own series."""
    return kdr_smiles(ABL_FROM_KDR[j]) if j in ABL_FROM_KDR else other_smiles("abl", j)


def merge(*outcomes: ExpectedOutcome) -> ExpectedOutcome:
    """Union of single-root expectations (one campaign each) into one multi-root expectation."""
    return ExpectedOutcome(
        campaign_roots=frozenset().union(*(o.campaign_roots for o in outcomes)),
        picked={k: v for o in outcomes for k, v in o.picked.items()},
        not_picked={k: v for o in outcomes for k, v in o.not_picked.items()},
        unknown={k: v for o in outcomes for k, v in o.unknown.items()},
        rest={k: v for o in outcomes for k, v in o.rest.items()},
        present={k: v for o in outcomes for k, v in o.present.items()},
    )


def scene(copyout: bool) -> tuple[TreeBuilder, SidecarBuilder]:
    """Tree and sidecar content of ``kdr_then_abl`` (``copyout=False``) or ``kdr_then_abl_copyout``."""
    tb = TreeBuilder(root="/vol3")
    sb = SidecarBuilder()
    analysis = kdr_campaign(tb, sb)
    ligand_campaign(tb, sb, ABL_ROOT, ABL_SPEC, abl_smiles,
                    name_of=lambda j: kdr_compound(ABL_FROM_KDR[j]) if j in ABL_FROM_KDR else f"ABL-{j:04d}")
    if copyout:
        pick_by_copy(tb, KDR_ROOT, analysis, ["run_lig012", "run_lig041"], rename="{id}_best.nc", uid=ANALYST,
                     mtime=at(workday(WD + 16), 14, 30))
        sb.mention(posixpath.join(analysis, "notes.txt"), "lig035", "candidate_id")
    return tb, sb


_ABL_NONE = ExpectedOutcome.campaign_no_selection(ABL_ROOT, ["cpd03"])
_BASE_TRUTH = merge(ExpectedOutcome.selection(KDR_ROOT, picked=["run_lig029"], rest="not_picked"), _ABL_NONE)

CONTENT = {
    "kdr_then_abl": lambda: scene(False)[1],
    "kdr_then_abl_copyout": lambda: scene(True)[1],
}
"""Sidecar content per scenario short name (read by ``content.sidecar.content_for``)."""

CONTENT_EXPECTED: dict[str, ExpectedOutcome] = {
    "kdr_then_abl": _BASE_TRUTH,
    "kdr_then_abl_copyout": merge(ExpectedOutcome.selection(
        KDR_ROOT, picked=["run_lig012", "run_lig029", "run_lig035", "run_lig041"], rest="not_picked"), _ABL_NONE),
}
"""What ``detect_with_content`` must report with the sidecars of :data:`CONTENT`."""


@register(
    kind="positive",
    description="KDR FEP lig029 picked only by identity: its InChIKey reappears as ABL_2013 cpd03 (content readers)",
    expected=_BASE_TRUTH,
    known_gap="graduation: lig029's only trace is its InChIKey reappearing under another name in ABL_2013; "
              "inventory-only detect cannot see identity (detect_with_content picks it, see test_content_pipeline)",
)
def build_kdr_then_abl() -> Inventory:
    """Build the KDR + ABL tree without inventory-visible picks."""
    return scene(False)[0].build()


@register(
    kind="positive",
    description="KDR FEP + ABL_2013: copies pick lig012/lig041; content adds lig029 (identity), lig035 (notes)",
    expected=merge(ExpectedOutcome.selection(KDR_ROOT, picked=["run_lig012", "run_lig041"], rest="not_picked"),
                   _ABL_NONE),
)
def build_kdr_then_abl_copyout() -> Inventory:
    """Build the KDR + ABL tree with two copy-out picks and a notes mention."""
    return scene(True)[0].build()
