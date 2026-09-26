#!/usr/bin/env python3
"""Summarise Emissary JSON output by family: one block per input file, children indented."""
import base64
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "build/localoutput/json")
SHOW = ["FILETYPE", "MIME_TYPE", "DESCENDANT_COUNT", "PARENT_FILETYPE", "ZIP_ENTRY_PATH", "ZIP_ENTRIES_EXTRACTED",
        "ZIP_ENTRIES_ENCRYPTED", "TITLE", "AUTHOR", "PAGE_COUNT", "LANGUAGE", "TEXT_CHARS", "TIKA_STATUS",
        "OCR_STATUS", "OCR_DETAIL", "OCR_PAGES", "OCR_INPUT_TOKENS", "OCR_OUTPUT_TOKENS", "OCR_MODEL"]


def one(p, key):
    v = p.get(key)
    return v[0] if isinstance(v, list) and len(v) == 1 else v


files = sorted(f for f in root.iterdir() if f.is_file() and not f.name.endswith(".bgjournal"))
families = []
for f in files:
    for line in f.read_text().splitlines():
        if line.strip():
            families.append(json.loads(line))

for fam in sorted(families, key=lambda fam: fam[0]["id"]):
    for rec in fam:
        depth = rec["id"].count("-att-")
        pad = "    " * depth
        p = {k.upper(): v for k, v in rec.get("parameters", {}).items()}
        print(f"{pad}{rec['id'].rsplit('/', 1)[-1]}  ({rec.get('channelSize')} bytes)")
        facts = [f"{k}={one(p, k)}" for k in SHOW if k in p]
        if facts:
            print(f"{pad}  " + "  ".join(facts))
        views = rec.get("views") or {}
        for name in ("TEXT", "OCR_TEXT"):
            if name in views:
                text = base64.b64decode(views[name]).decode("utf-8", "replace").strip().replace("\n", " | ")
                print(f"{pad}  {name}: {text[:150]}{'...' if len(text) > 150 else ''}")
        hist = [h["key"].split(".")[1] for h in rec.get("transformHistory", {}).get("history", [])]
        print(f"{pad}  route: {' > '.join(hist)}")
        if p.get("PROCESSING_ERROR") or rec.get("processingError"):
            print(f"{pad}  errors: {p.get('PROCESSING_ERROR') or rec.get('processingError')}")
    print()
print(f"{len(families)} families, {sum(len(f) for f in families)} records")
