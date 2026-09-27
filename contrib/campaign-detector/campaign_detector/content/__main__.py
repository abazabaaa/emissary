"""Command line: ``python -m campaign_detector.content <subcommand> [options]``.

* ``manifest --inventory FILE [--json]``: candidate records (file manifest per candidate);
* ``sidecar --scenario NAME --out-dir DIR``: write a scenario's sidecar TSVs;
* ``detect --inventory FILE --content-dir DIR [--json]``: two-pass detection with the sidecar reader;
* ``winner --inventory FILE --content-dir DIR --out FILE.tsv``: winner feature rows.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Callable, Sequence

from ..cli import format_report
from ..detect import detect
from ..inventory import Inventory
from ..scenarios import get
from . import sidecar
from .fake import fake_registry
from .manifest import candidate_records
from .pipeline import run_content
from .winner import winner_rows, write_winner_tsv


def cmd_manifest(argv: Sequence[str]) -> int:
    """``manifest --inventory FILE [--json]`` lists each candidate's files by content class."""
    ap = argparse.ArgumentParser(prog="campaign_detector.content manifest", description=cmd_manifest.__doc__)
    ap.add_argument("--inventory", required=True, help="inventory TSV")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = ap.parse_args(argv)
    inv = Inventory.from_tsv(args.inventory)
    records = candidate_records(inv, detect(inv))
    if args.json:
        out = [{**{k: v for k, v in dataclasses.asdict(r).items() if k != "files"}, "key": r.key,
                "files": {cls: [dataclasses.asdict(f) for f in refs] for cls, refs in r.files.items()}}
               for r in records]
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    if not records:
        print("no campaign detected")
    for r in records:
        counts = "  ".join(f"{cls}:{len(refs)}" for cls, refs in r.files.items())
        fmts = sorted({f.fmt for refs in r.files.values() for f in refs})
        print(f"{r.key}\t{r.engine}\t{r.unit}\t{r.label}\t{counts}\t{','.join(fmts)}")
    return 0


def cmd_sidecar(argv: Sequence[str]) -> int:
    """``sidecar --scenario NAME --out-dir DIR`` writes ligands.tsv, metrics.tsv and mentions.tsv."""
    ap = argparse.ArgumentParser(prog="campaign_detector.content sidecar", description=cmd_sidecar.__doc__)
    ap.add_argument("--scenario", required=True, help="scenario name (python -m campaign_detector synth --list)")
    ap.add_argument("--out-dir", required=True, help="output directory")
    args = ap.parse_args(argv)
    scenario = get(args.scenario)
    if sidecar.content_for(scenario) is None:
        print(f"note: {scenario.name} declares no CONTENT; writing empty sidecars", file=sys.stderr)
    counts = sidecar.write(scenario, args.out_dir)
    print("  ".join(f"{name} {n}" for name, n in counts.items()))
    return 0


def cmd_detect(argv: Sequence[str]) -> int:
    """``detect --inventory FILE --content-dir DIR [--json]`` runs detection with content hooks."""
    ap = argparse.ArgumentParser(prog="campaign_detector.content detect", description=cmd_detect.__doc__)
    ap.add_argument("--inventory", required=True, help="inventory TSV")
    ap.add_argument("--content-dir", required=True, help="directory with sidecar TSVs")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = ap.parse_args(argv)
    inv = Inventory.from_tsv(args.inventory)
    run = run_content(inv, fake_registry(args.content_dir))
    if args.json:
        print(json.dumps(run.result.to_dict(), indent=2, sort_keys=True))
        return 0
    n_ident = sum(1 for c in run.contents.values() if c.best is not None)
    print(f"content: {len(run.records)} candidates, {n_ident} with a ligand identity, "
          f"{len(run.loose)} loose results, {len(run.graduation)} identity occurrences, "
          f"{len(run.mentions)} mentions")
    if not run.result.campaigns:
        print("no campaign detected")
    else:
        print("\n\n".join(format_report(r) for r in run.result.campaigns))
    return 0


def cmd_winner(argv: Sequence[str]) -> int:
    """``winner --inventory FILE --content-dir DIR --out FILE.tsv`` writes one feature row per candidate."""
    ap = argparse.ArgumentParser(prog="campaign_detector.content winner", description=cmd_winner.__doc__)
    ap.add_argument("--inventory", required=True, help="inventory TSV")
    ap.add_argument("--content-dir", required=True, help="directory with sidecar TSVs")
    ap.add_argument("--out", required=True, help="output TSV path")
    args = ap.parse_args(argv)
    inv = Inventory.from_tsv(args.inventory)
    run = run_content(inv, fake_registry(args.content_dir))
    rows = winner_rows(run.result, run.contents, records=run.records)
    write_winner_tsv(rows, args.out)
    print(f"wrote {len(rows)} rows to {args.out}")
    return 0


SUBCOMMANDS: dict[str, Callable[[Sequence[str]], int]] = {
    "manifest": cmd_manifest,
    "sidecar": cmd_sidecar,
    "detect": cmd_detect,
    "winner": cmd_winner,
}
"""Subcommand name -> handler taking the remaining argv and returning an exit code."""


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch ``argv`` (default ``sys.argv[1:]``) to a subcommand; returns the exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in SUBCOMMANDS:
        print("usage: python -m campaign_detector.content {" + ",".join(SUBCOMMANDS) + "} [options]",
              file=sys.stderr)
        for name, fn in SUBCOMMANDS.items():
            print(f"  {name:<9} {(fn.__doc__ or '').strip()}", file=sys.stderr)
        return 0 if args[:1] in (["-h"], ["--help"]) else 2
    return SUBCOMMANDS[args[0]](args[1:])


if __name__ == "__main__":
    sys.exit(main())
