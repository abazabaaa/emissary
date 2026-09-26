#!/usr/bin/env python3
"""Pack out/graph.json into a compact dataset and embed it in explorer.template.html -> out/explorer.html."""
import json
import pathlib
import subprocess
import sys

here = pathlib.Path(__file__).parent
out = here / "out"
g = json.loads((out / "graph.json").read_text())
repo = g["meta"]["repo"]
sha = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
remote = subprocess.run(["git", "-C", repo, "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
slug = "abazabaaa/emissary"
if "github.com" in remote:
    slug = remote.split("github.com", 1)[1].strip(":/").removesuffix(".git")
    slug = "/".join(slug.split("/")[-2:])

main = [n for n in g["nodes"] if n.get("set") == "main"]
other = [n for n in g["nodes"] if n.get("set") != "main"]
ids = [n["id"] for n in main] + [n["id"] for n in other]
idx = {i: k for k, i in enumerate(ids)}
tests = g["tests"]
tidx = {t["id"]: k for k, t in enumerate(tests)}
kinds = sorted({e["kind"] for e in g["edges"]})
kidx = {k: i for i, k in enumerate(kinds)}
place_ids = {p["id"] for p in g["places"]}

classes = []
for n in main:
    classes.append({
        "id": n["id"], "n": n["name"], "p": n["pkg"], "k": n["kind"], "f": n["file"], "loc": n["loc"],
        "cx": n["complexity"], "m": n["methods"], "doc": n.get("doc", ""), "ch": n.get("churn", 0),
        "ch2": n.get("churn2y", 0), "fi": n.get("fanIn", 0), "fo": n.get("fanOut", 0),
        "t": [tidx[t] for t in n.get("tests", []) if t in tidx], "dt": n.get("directTest", False),
        "uc": n.get("useCases", []), "en": n.get("entry", []), "cm": n.get("community", -1),
        "ep": n.get("endpoints", []), "cmd": n.get("command"), "dep": n.get("deprecated", False),
        "hs": n.get("hotspot", 0), "pl": n["id"] in place_ids, "rch": n.get("reachable", True),
        "anc": n.get("ancestors", []),
    })
others = [{"id": n["id"], "n": n["name"], "k": n["kind"], "f": n.get("file", ""), "fl": n.get("flavor")} for n in other]
edges = [[idx[e["s"]], idx[e["t"]], kidx[e["kind"]]] for e in g["edges"] if e["s"] in idx and e["t"] in idx]

data = {
    "meta": {**g["meta"], "sha": sha, "slug": slug, "packagesTotal": len(g["packages"])},
    "classes": classes, "others": others, "edges": edges, "kinds": kinds,
    "tests": [{"id": t["id"], "n": t["name"], "f": t["file"], "doc": t["doc"]} for t in tests],
    "packages": g["packages"], "packageEdges": g["packageEdges"], "sccs": g["sccs"],
    "communities": [{k: v for k, v in c.items()} for c in g["communities"]],
    "places": g["places"], "useCases": g["useCases"], "findings": g["findings"], "inventory": g["inventory"],
}
payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
tpl = (here / "explorer.template.html").read_text()
html = tpl.replace("/*__DATA__*/null", payload)
(out / "explorer.html").write_text(html)
print(f"wrote {out / 'explorer.html'} ({len(html) / 1024:.0f} KB), {len(classes)} classes, {len(edges)} edges", file=sys.stderr)
