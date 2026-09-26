#!/usr/bin/env python3
"""Emissary code + config graph analyzer.

Builds a multi-layer dependency graph of the Emissary codebase:
  * code layer    - Java ASTs (tree-sitter): extends / implements / new / uses / reflect (FQN string literals)
  * wiring layer  - Jersey package scanning, java.util.ServiceLoader (META-INF/services)
  * config layer  - .cfg files: class names in values, places.cfg deployments, ClassNameInventory, place routing keys
  * test layer    - which test classes reference which main classes
  * history layer - per-file commit churn from a (blob-less) clone of the upstream repository

Usage: analyze.py --repo /path/to/emissary [--history /path/to/emissary.git] --out out/
"""
import argparse
import collections
import json
import pathlib
import re
import subprocess

import networkx as nx
import tree_sitter_java as tsj
from tree_sitter import Language, Parser

PARSER = Parser(Language(tsj.language()))
TYPE_DECLS = ("class_declaration", "interface_declaration", "enum_declaration", "record_declaration",
              "annotation_type_declaration")
BRANCH_NODES = {"if_statement", "for_statement", "enhanced_for_statement", "while_statement", "do_statement",
                "catch_clause", "ternary_expression", "switch_label", "switch_rule"}
FQN_RE = re.compile(r"^emissary(\.[A-Za-z_]\w*)+$")
HTTP_VERBS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"}
# Packages whose classes are shared plumbing; use-case slices stop expanding at them.
INFRA_PACKAGES = ("emissary.config", "emissary.util", "emissary.log", "emissary.metrics")
INFRA_CLASSES = {"emissary.core.Namespace", "emissary.core.NamespaceException", "emissary.core.EmissaryException",
                 "emissary.core.EmissaryRuntimeException", "emissary.core.Factory", "emissary.core.Form"}


def txt(n):
    return n.text.decode("utf-8", "replace")


def walk(n):
    stack = [n]
    while stack:
        cur = stack.pop()
        yield cur
        stack.extend(reversed(cur.children))


def pkg_of(fqn):
    return fqn.rsplit(".", 1)[0]


def is_infra(fqn):
    return fqn in INFRA_CLASSES or any(fqn == p or fqn.startswith(p + ".") for p in INFRA_PACKAGES)


# ----------------------------------------------------------------------------------------------------------------------
# Java parsing
# ----------------------------------------------------------------------------------------------------------------------

def annotations_of(decl):
    out = []
    for c in decl.children:
        if c.type == "modifiers":
            for a in c.children:
                if a.type in ("marker_annotation", "annotation"):
                    name = txt(a.child_by_field_name("name"))
                    args = a.child_by_field_name("arguments")
                    out.append((name, txt(args) if args else ""))
    return out


def modifiers_of(decl):
    for c in decl.children:
        if c.type == "modifiers":
            return {txt(k) for k in c.children if k.type not in ("marker_annotation", "annotation")}
    return set()


def javadoc_of(decl):
    prev = decl.prev_named_sibling
    if prev is not None and prev.type in ("block_comment", "comment") and txt(prev).startswith("/**"):
        body = re.sub(r"^\s*/?\*+/?", "", txt(prev), flags=re.M)
        body = re.sub(r"\{@\w+\s+([^}]*)\}", r"\1", body)
        body = re.sub(r"<[^>]+>", "", body)
        body = " ".join(line.strip() for line in body.splitlines() if not line.strip().startswith("@"))
        body = re.sub(r"\s+", " ", body).strip()
        m = re.match(r"(.+?[.!?])(\s|$)", body)
        return (m.group(1) if m else body)[:300]
    return ""


def string_value(annotation_args):
    m = re.findall(r'"([^"]*)"', annotation_args)
    return m[0] if m else ""


def parse_java_tree(root: pathlib.Path, source_set: str):
    """Returns (types: dict fqn -> info, raw: dict fqn -> parse artefacts for edge extraction)."""
    types, raw = {}, {}
    for f in sorted(root.rglob("*.java")):
        data = f.read_bytes()
        tree = PARSER.parse(data)
        top = tree.root_node
        pkg = ""
        imports, static_imports = {}, []
        for c in top.children:
            if c.type == "package_declaration":
                pkg = txt(c.named_children[-1]) if c.named_children else ""
                for nc in c.named_children:
                    if nc.type in ("scoped_identifier", "identifier"):
                        pkg = txt(nc)
            elif c.type == "import_declaration":
                t = txt(c)
                name = re.sub(r"^import\s+(static\s+)?|;$", "", t).strip()
                if " static " in f" {t} ":
                    static_imports.append(name.rsplit(".", 1)[0])
                elif not name.endswith(".*"):
                    imports[name.rsplit(".", 1)[-1]] = name
        decls = [c for c in top.children if c.type in TYPE_DECLS]
        if not decls:
            continue
        rel = str(f.relative_to(root.parent.parent.parent))  # src/<set>/java/...
        for decl in decls:
            name = txt(decl.child_by_field_name("name"))
            fqn = f"{pkg}.{name}" if pkg else name
            mods = modifiers_of(decl)
            anns = annotations_of(decl)
            kind = {"class_declaration": "class", "interface_declaration": "interface", "enum_declaration": "enum",
                    "record_declaration": "record", "annotation_type_declaration": "annotation"}[decl.type]
            if kind == "class" and "abstract" in mods:
                kind = "abstract"
            methods, public_methods, has_main, complexity = 0, 0, False, 1
            endpoints, nested = [], []
            class_path = next((string_value(a) for n, a in anns if n == "Path"), None)
            for n in walk(decl):
                t = n.type
                if t in BRANCH_NODES:
                    complexity += 1
                elif t == "binary_expression":
                    op = n.child_by_field_name("operator")
                    if op is not None and txt(op) in ("&&", "||"):
                        complexity += 1
                elif t in ("method_declaration", "constructor_declaration"):
                    methods += 1
                    mm = modifiers_of(n)
                    if "public" in mm:
                        public_methods += 1
                    if t == "method_declaration" and txt(n.child_by_field_name("name")) == "main" and "static" in mm:
                        has_main = True
                    if t == "method_declaration":
                        manns = annotations_of(n)
                        verbs = [a for a, _ in manns if a in HTTP_VERBS]
                        if verbs:
                            mpath = next((string_value(a) for x, a in manns if x == "Path"), "")
                            full = "/" + "/".join(p.strip("/") for p in (class_path or "", mpath) if p and p.strip("/"))
                            endpoints.append({"verb": verbs[0], "path": full, "method": txt(n.child_by_field_name("name"))})
                elif t in TYPE_DECLS and n is not decl:
                    nested.append(txt(n.child_by_field_name("name")))
            cmd = next((a for n, a in anns if n == "Command"), None)
            cmd_name = None
            if cmd:
                m = re.search(r'name\s*=\s*"([^"]+)"', cmd)
                cmd_name = m.group(1) if m else None
            extends, implements = [], []
            for c in decl.children:
                if c.type == "superclass":
                    extends += [x for x in c.named_children]
                elif c.type in ("super_interfaces", "extends_interfaces"):
                    implements += [x for x in walk(c) if x.type == "type_list"][0].named_children if any(
                        x.type == "type_list" for x in walk(c)) else []
            if kind == "interface":  # interface "extends" is modelled as extends
                extends, implements = implements, []
            types[fqn] = {
                "id": fqn, "name": name, "pkg": pkg, "kind": kind, "set": source_set, "file": rel,
                "loc": data.count(b"\n") + 1, "methods": methods, "publicMethods": public_methods,
                "complexity": complexity, "doc": javadoc_of(decl), "main": has_main,
                "public": "public" in mods, "deprecated": any(n == "Deprecated" for n, _ in anns),
                "annotations": sorted({n for n, _ in anns}), "endpoints": endpoints, "command": cmd_name,
                "nested": nested,
            }
            raw[fqn] = {"decl": decl, "imports": imports, "static_imports": static_imports, "pkg": pkg,
                        "extends": extends, "implements": implements}
    return types, raw


def type_names_in(node):
    """Yield simple/qualified type names referenced by a type node."""
    for n in walk(node):
        if n.type == "type_identifier":
            p = n.parent
            if p is not None and p.type == "scoped_type_identifier":
                continue
            yield txt(n)
        elif n.type == "scoped_type_identifier":
            if n.parent is not None and n.parent.type == "scoped_type_identifier":
                continue
            yield txt(n)


def extract_edges(types_all, raw, simple_index, source_types):
    """Returns list of (src, tgt, kind) and list of unresolved emissary FQN strings (src, literal)."""
    edges, unresolved = [], []

    def resolve(name, info):
        name = re.sub(r"<.*", "", name)
        if name in types_all:
            return name
        head = name.split(".")[0]
        if head in info["imports"]:
            cand = info["imports"][head]
            return cand if cand in types_all else None
        same = f"{info['pkg']}.{head}"
        if same in types_all:
            return same
        return None

    for src in source_types:
        info = raw[src]
        decl = info["decl"]
        seen = set()

        def add(tgt, kind):
            if tgt and tgt != src and tgt.startswith("emissary") and (tgt, kind) not in seen:
                seen.add((tgt, kind))
                edges.append((src, tgt, kind))

        for t in info["extends"]:
            for nm in type_names_in(t):
                add(resolve(nm, info), "extends")
        for t in info["implements"]:
            for nm in type_names_in(t):
                add(resolve(nm, info), "implements")
        for s in info["static_imports"]:
            add(s if s in types_all else None, "uses")
        for n in walk(decl):
            t = n.type
            if t == "object_creation_expression":
                ty = n.child_by_field_name("type")
                if ty is not None:
                    for nm in type_names_in(ty):
                        add(resolve(nm, info), "new")
            elif t in ("type_identifier", "scoped_type_identifier"):
                if t == "type_identifier" and n.parent is not None and n.parent.type == "scoped_type_identifier":
                    continue
                add(resolve(txt(n), info), "uses")
            elif t in ("method_invocation", "field_access"):
                obj = n.child_by_field_name("object")
                if obj is not None and obj.type == "identifier" and txt(obj)[:1].isupper():
                    add(resolve(txt(obj), info), "uses")
            elif t == "string_literal":
                s = txt(n).strip('"')
                if FQN_RE.match(s):
                    if s in types_all:
                        add(s, "reflect")
                    elif s.rsplit(".", 1)[-1][:1].isupper() and s not in simple_index.get("__pkgs__", set()):
                        unresolved.append((src, s))
    return edges, unresolved


# ----------------------------------------------------------------------------------------------------------------------
# Config parsing
# ----------------------------------------------------------------------------------------------------------------------

CFG_LINE = re.compile(r'^\s*"?([A-Za-z0-9_.\-@{}]+)"?\s*(!?=)\s*(.*?)\s*$')


def parse_cfg(path: pathlib.Path):
    entries = []
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = CFG_LINE.match(s)
        if not m:
            continue
        key, op, val = m.groups()
        val = val.strip()
        if val.startswith('"') and val.endswith('"') and len(val) >= 2:
            val = val[1:-1]
        entries.append((key, op, val))
    return entries


def cfg_owner(path: pathlib.Path, repo: pathlib.Path):
    """Map a cfg file to (owner_fqn_or_None, flavor, logical_name)."""
    rel = path.relative_to(repo).as_posix()
    stem = path.name[:-4]
    flavor = None
    m = re.match(r"^(.*?)-([A-Za-z0-9]+)$", stem)
    if m and (m.group(2).isupper() or m.group(2) == "test"):
        stem, flavor = m.group(1), m.group(2)
    if "/resources/" in rel:
        pkg_path = rel.split("/resources/", 1)[1].rsplit("/", 1)[0].replace("/", ".")
        return f"{pkg_path}.{stem}", flavor, stem
    if stem.startswith("emissary."):
        return stem, flavor, stem
    return None, flavor, stem


def parse_service_key(key):
    # FORM.SERVICE_NAME.STAGE.URL$COST  (URL itself contains dots)
    m = re.match(r"^([^.]+)\.([^.]+)\.([^.]+)\.(.+?)(?:\$(\d+))?$", key)
    if not m:
        return None
    form, name, stage, url, cost = m.groups()
    return {"form": form, "service": name, "stage": stage, "place": url.rsplit("/", 1)[-1],
            "cost": int(cost) if cost else None}


# ----------------------------------------------------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--history", help="git dir with full history (e.g. a --filter=blob:none bare clone)")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()
    repo = pathlib.Path(args.repo).resolve()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    main_types, main_raw = parse_java_tree(repo / "src/main/java", "main")
    test_types, test_raw = parse_java_tree(repo / "src/test/java", "test")
    all_types = {**main_types, **test_types}
    all_raw = {**main_raw, **test_raw}
    simple_index = collections.defaultdict(set)
    for fqn in main_types:
        simple_index[fqn.rsplit(".", 1)[-1]].add(fqn)
    simple_index["__pkgs__"] = {t["pkg"] for t in all_types.values()}

    code_edges, unresolved_code = extract_edges(main_types, main_raw, simple_index, list(main_types))
    test_edges, _ = extract_edges(all_types, all_raw, simple_index, list(test_types))

    G = nx.MultiDiGraph()
    for fqn, t in main_types.items():
        G.add_node(fqn, **{k: v for k, v in t.items() if k not in ("nested",)})
    for s, d, k in code_edges:
        G.add_edge(s, d, kind=k, layer="code")

    findings = collections.defaultdict(list)
    cfg_stems = {f.name[:-4] for f in list((repo / "src/main/config").glob("*.cfg"))}
    for src, lit in unresolved_code:
        if lit in cfg_stems:
            continue  # a config name, linked below as reads-config
        findings["unresolvedClassRefs"].append({"source": src, "ref": lit, "where": "java string literal"})

    # --- wiring: Jersey package scanning --------------------------------------------------------------------------
    server_src = (repo / "src/main/java/emissary/server/EmissaryServer.java").read_text()
    scanned = re.findall(r'\.packages\("([^"]+)"\)', server_src)
    for fqn, t in main_types.items():
        if any(t["pkg"] == p or t["pkg"].startswith(p + ".") for p in scanned) and \
                ("Path" in t["annotations"] or t["endpoints"]):
            G.add_edge("emissary.server.EmissaryServer", fqn, kind="scan", layer="wiring")

    # --- wiring: ServiceLoader -----------------------------------------------------------------------------------
    spi = {}
    for f in (repo / "src/main/resources/META-INF/services").glob("*"):
        iface = f.name
        provs = [l.strip() for l in f.read_text().splitlines() if l.strip() and not l.startswith("#")]
        spi[iface] = provs
        for p in provs:
            if p in main_types:
                G.add_edge(iface if iface in main_types else "emissary.spi.SPILoader", p, kind="spi", layer="wiring")

    # --- config layer --------------------------------------------------------------------------------------------
    cfg_files = sorted(list((repo / "src/main/resources").rglob("*.cfg")) + list((repo / "src/main/config").glob("*.cfg")))
    configs = {}
    inventory = {}
    for f in cfg_files:
        owner, flavor, stem = cfg_owner(f, repo)
        entries = parse_cfg(f)
        cid = "cfg:" + f.relative_to(repo).as_posix()
        configs[cid] = {"id": cid, "file": f.relative_to(repo).as_posix(), "owner": owner if owner in main_types else None,
                        "ownerName": owner, "flavor": flavor, "stem": stem, "entries": entries}
        if stem.endswith("ClassNameInventory"):
            for k, op, v in entries:
                if op == "=":
                    inventory[k] = v
    # config nodes + edges
    for cid, c in configs.items():
        G.add_node(cid, id=cid, name=pathlib.Path(c["file"]).name, pkg="(config)", kind="config", set="config",
                   file=c["file"], flavor=c["flavor"])
        if c["owner"]:
            G.add_edge(c["owner"], cid, kind="configured-by", layer="config")
        elif c["ownerName"] and c["ownerName"].startswith("emissary."):
            findings["orphanConfigs"].append({"config": c["file"], "expectedClass": c["ownerName"]})
        for k, op, v in c["entries"]:
            if op != "=":
                continue
            for lit in re.findall(r"emissary(?:\.[A-Za-z_]\w*)+", v):
                if lit in main_types:
                    G.add_edge(cid, lit, kind="config-ref", layer="config", key=k)
                elif lit.rsplit(".", 1)[-1][:1].isupper():
                    findings["unresolvedClassRefs"].append({"source": c["file"], "ref": lit, "where": f"cfg key {k}"})
    # places.cfg deployments
    deployments = collections.defaultdict(list)
    for cid, c in configs.items():
        if c["stem"] != "places":
            continue
        for k, op, v in c["entries"]:
            if k == "PLACE" and op == "=":
                short = v.rsplit("/", 1)[-1]
                fqn = inventory.get(short)
                flavor = c["flavor"] or "default"
                deployments[short].append(flavor)
                if fqn in main_types:
                    G.add_edge(cid, fqn, kind="deploys", layer="config")
                else:
                    findings["unresolvedClassRefs"].append({"source": c["file"], "ref": short,
                                                            "where": "PLACE not resolvable via ClassNameInventory"})

    # java literal naming a config file -> reads-config
    by_stem = collections.defaultdict(list)
    for cid, c in configs.items():
        by_stem[c["stem"]].append(cid)
    for src, lit in unresolved_code:
        for cid in by_stem.get(lit, []):
            G.add_edge(src, cid, kind="reads-config", layer="config")

    # other resources (logback.xml, properties, templates, launcher script) and commented-out cfg lines
    commented_refs = collections.defaultdict(list)
    resource_files = [f for f in list((repo / "src/main/config").iterdir()) + list((repo / "src/main/resources").rglob("*"))
                      if f.is_file() and f.suffix in (".xml", ".properties", ".mustache", ".html", ".sh", ".yaml", ".yml")]
    resource_files.append(repo / "emissary")
    for f in resource_files:
        rel = f.relative_to(repo).as_posix()
        for lit in set(re.findall(r"emissary(?:\.[A-Za-z_]\w*)+", f.read_text(errors="replace"))):
            if lit in main_types:
                rid = "res:" + rel
                if rid not in G:
                    G.add_node(rid, id=rid, name=f.name, pkg="(resource)", kind="resource", set="config", file=rel)
                G.add_edge(rid, lit, kind="resource-ref", layer="config")
    for f in cfg_files:
        for line in f.read_text(errors="replace").splitlines():
            if line.strip().startswith("#"):
                for lit in re.findall(r"emissary(?:\.[A-Za-z_]\w*)+", line):
                    if lit in main_types:
                        commented_refs[lit].append(f.relative_to(repo).as_posix())

    # --- place routing (form -> place -> form) ------------------------------------------------------------------
    place_bases = {"emissary.place.ServiceProviderPlace", "emissary.place.IServiceProviderPlace"}
    ext = collections.defaultdict(set)
    for s, d, k in code_edges:
        if k in ("extends", "implements"):
            ext[s].add(d)

    def ancestors(fqn, acc=None):
        acc = acc if acc is not None else set()
        for p in ext.get(fqn, ()):
            if p not in acc:
                acc.add(p)
                ancestors(p, acc)
        return acc

    for fqn in main_types:
        main_types[fqn]["ancestors"] = sorted(ancestors(fqn))
        G.nodes[fqn]["ancestors"] = main_types[fqn]["ancestors"]
    places = {}
    for fqn, t in main_types.items():
        if not (place_bases & set(t["ancestors"])) or t["kind"] in ("interface",):
            continue
        cfgs = [c for c in configs.values() if c["owner"] == fqn and c["flavor"] != "test"]  # -test = fixtures
        keys, emits, desc = [], set(), ""
        for c in cfgs:
            flv = c["flavor"]
            proxies, stage, service, cost = [], None, None, None
            for k, op, v in c["entries"]:
                if op != "=":
                    continue
                if k == "SERVICE_KEY":
                    sk = parse_service_key(v)
                    if sk:
                        keys.append({**sk, "flavor": flv})
                elif k == "SERVICE_PROXY":
                    proxies.append(v)
                elif k == "SERVICE_TYPE":
                    stage = v
                elif k == "SERVICE_NAME":
                    service = v
                elif k == "SERVICE_COST":
                    cost = int(v) if v.isdigit() else None
                elif k == "SERVICE_DESCRIPTION":
                    desc = v
                elif k.endswith("_FORM") and v and v != "*":
                    emits.add((v, flv or ""))
            if proxies and (stage is None or service is None):  # flavor file overriding only the proxy
                base = next((b for b in keys if b["flavor"] is None), None)
                stage = stage or (base or {}).get("stage")
                service = service or (base or {}).get("service")
            for px in proxies:
                keys.append({"form": px, "service": service, "stage": stage, "place": t["name"], "cost": cost,
                             "flavor": flv})
        uniq = {}
        for k in keys:
            uniq[(k["form"], k["stage"], k["flavor"])] = k
        keys = list(uniq.values())
        places[fqn] = {"id": fqn, "name": t["name"], "abstract": t["kind"] != "class", "keys": keys,
                       "emits": [{"form": f_, "flavor": fl or None} for f_, fl in sorted(emits)], "description": desc,
                       "deployed": deployments.get(t["name"], []),
                       "inInventory": t["name"] in inventory}

    # --- test layer ----------------------------------------------------------------------------------------------
    tested_by = collections.defaultdict(set)
    for s, d, k in test_edges:
        if d in main_types:
            tested_by[d].add(s)
    for fqn in main_types:
        G.nodes[fqn]["tests"] = sorted(tested_by.get(fqn, ()))
    # direct test = a test class named <Class>Test / <Class>IT
    test_names = {t["name"] for t in test_types.values()}
    for fqn, t in main_types.items():
        G.nodes[fqn]["directTest"] = any(n in test_names for n in (t["name"] + "Test", t["name"] + "IT"))

    # --- history layer -------------------------------------------------------------------------------------------
    churn = collections.Counter()
    history_meta = None
    if args.history:
        log = subprocess.run(["git", "--git-dir", args.history, "log", "--no-renames", "--name-only",
                              "--format=@@%ad", "--date=short", "HEAD"], capture_output=True, text=True, check=True).stdout
        dates, commits = [], 0
        recent = collections.Counter()
        for line in log.splitlines():
            if line.startswith("@@"):
                commits += 1
                cur_date = line[2:]
                dates.append(cur_date)
            elif line.endswith(".java") and line.startswith("src/main/java/"):
                churn[line] += 1
                if cur_date >= "2024-09-25":
                    recent[line] += 1
        history_meta = {"commits": commits, "first": min(dates), "last": max(dates)}
        for fqn, t in main_types.items():
            G.nodes[fqn]["churn"] = churn.get(t["file"], 0)
            G.nodes[fqn]["churn2y"] = recent.get(t["file"], 0)

    # --- analyses ------------------------------------------------------------------------------------------------
    D = nx.DiGraph()  # collapsed, all layers except tests
    for s, d, data in G.edges(data=True):
        if D.has_edge(s, d):
            D[s][d]["kinds"].add(data["kind"])
        else:
            D.add_edge(s, d, kinds={data["kind"]})
    for n in G.nodes:
        D.add_node(n)

    code_only = nx.DiGraph()
    code_only.add_nodes_from(main_types)
    for s, d, k in code_edges:
        code_only.add_edge(s, d)

    roots = set()
    root_reason = collections.defaultdict(list)

    def root(fqn, why):
        roots.add(fqn)
        root_reason[fqn].append(why)

    root("emissary.Emissary", "launched by ./emissary script")
    for fqn, t in main_types.items():
        if t["main"]:
            root(fqn, "has main()")
    for cid, c in configs.items():
        if c["stem"] in ("places", "ClassNameInventory", "emissary.admin.ClassNameInventory") or \
                c["file"].startswith("src/main/config/"):
            root(cid, "runtime config file")
    for iface, provs in spi.items():
        for p in provs:
            if p in main_types:
                root(p, f"ServiceLoader provider of {iface}")

    reachable = set()
    for r in roots:
        if r in D:
            reachable |= {r} | nx.descendants(D, r)

    for fqn, t in main_types.items():
        G.nodes[fqn]["fanIn"] = code_only.in_degree(fqn)
        G.nodes[fqn]["fanOut"] = code_only.out_degree(fqn)
        G.nodes[fqn]["reachable"] = fqn in reachable
        G.nodes[fqn]["entry"] = root_reason.get(fqn, [])

    def classify(fqn):
        t = main_types[fqn]
        anc = set(t.get("ancestors", []))
        if t["kind"] in ("interface", "abstract", "annotation"):
            return "extension point"
        if place_bases & anc:
            return "place (enabled via config)"
        if any(a.startswith("emissary.core.sentinel.protocols.") for a in anc):
            return "sentinel plugin (named in config)"
        if fqn in commented_refs:
            return "opt-in (only in commented-out config)"
        if tested_by.get(fqn):
            return "library utility (tests only)"
        return "no references found"

    # unreferenced classes
    for fqn, t in sorted(main_types.items()):
        inbound = [s for s in D.predecessors(fqn)]
        if fqn in roots:
            continue
        if not inbound:
            findings["unreferenced"].append({
                "class": fqn, "kind": t["kind"], "public": t["public"], "loc": t["loc"],
                "tests": len(tested_by.get(fqn, ())),
                "category": classify(fqn), "commentedIn": commented_refs.get(fqn, [])})
        elif fqn not in reachable:
            findings["unreachable"].append({"class": fqn, "kind": t["kind"], "loc": t["loc"],
                                            "category": classify(fqn), "referencedBy": sorted(inbound)[:8]})

    # package graph + cycles
    P = nx.DiGraph()
    pkg_stats = collections.defaultdict(lambda: {"classes": 0, "loc": 0, "abstract": 0, "tested": 0, "churn": 0,
                                                  "complexity": 0})
    for fqn, t in main_types.items():
        ps = pkg_stats[t["pkg"]]
        ps["classes"] += 1
        ps["loc"] += t["loc"]
        ps["complexity"] += t["complexity"]
        ps["abstract"] += t["kind"] in ("interface", "abstract")
        ps["tested"] += bool(tested_by.get(fqn))
        ps["churn"] += G.nodes[fqn].get("churn", 0)
        P.add_node(t["pkg"])
    edge_detail = collections.defaultdict(list)
    for s, d, k in code_edges:
        a, b = main_types[s]["pkg"], main_types[d]["pkg"]
        if a != b:
            edge_detail[(a, b)].append((s, d))
    for (a, b), lst in edge_detail.items():
        P.add_edge(a, b, weight=len(lst))
    for p in P.nodes:
        ce, ca = P.out_degree(p), P.in_degree(p)
        s = pkg_stats[p]
        s["ce"], s["ca"] = ce, ca
        s["instability"] = round(ce / (ca + ce), 2) if ca + ce else 0
        s["abstractness"] = round(s["abstract"] / s["classes"], 2) if s["classes"] else 0
        s["distance"] = round(abs(s["abstractness"] + s["instability"] - 1), 2)
    sccs = [sorted(c) for c in nx.strongly_connected_components(P) if len(c) > 1]
    sccs.sort(key=len, reverse=True)
    # For each cyclic package pair, the class edges that close the loop
    cycle_pairs = []
    for comp in sccs:
        cs = set(comp)
        for a in comp:
            for b in comp:
                if a < b and P.has_edge(a, b) and P.has_edge(b, a):
                    cycle_pairs.append({"a": a, "b": b, "ab": [list(x) for x in edge_detail[(a, b)][:6]],
                                        "ba": [list(x) for x in edge_detail[(b, a)][:6]],
                                        "weightAB": len(edge_detail[(a, b)]), "weightBA": len(edge_detail[(b, a)])})
    cycle_pairs.sort(key=lambda x: min(x["weightAB"], x["weightBA"]))

    # communities (emergent subsystems)
    U = code_only.to_undirected()
    comms = nx.community.louvain_communities(U, seed=7, resolution=1.0)
    comm_of = {}
    communities = []
    for i, c in enumerate(sorted(comms, key=len, reverse=True)):
        pk = collections.Counter(main_types[n]["pkg"] for n in c)
        hub = max(c, key=lambda n: code_only.in_degree(n))
        communities.append({"id": i, "size": len(c), "packages": pk.most_common(6), "hub": hub, "members": sorted(c)})
        for n in c:
            comm_of[n] = i
    for fqn in main_types:
        G.nodes[fqn]["community"] = comm_of.get(fqn, -1)

    # hotspots: churn x complexity (normalised ranks)
    if args.history:
        mc = max(1, max(G.nodes[f].get("churn", 0) for f in main_types))
        mx = max(1, max(t["complexity"] for t in main_types.values()))
        hs = []
        for fqn, t in main_types.items():
            score = (G.nodes[fqn]["churn"] / mc) * (t["complexity"] / mx)
            G.nodes[fqn]["hotspot"] = round(score, 4)
            hs.append((score, fqn))
        findings["hotspots"] = [{"class": f, "score": round(s, 3), "churn": G.nodes[f]["churn"],
                                 "complexity": main_types[f]["complexity"], "loc": main_types[f]["loc"],
                                 "tests": len(tested_by.get(f, ()))} for s, f in sorted(hs, reverse=True)[:25]]

    findings["untestedComplex"] = sorted(
        [{"class": f, "complexity": t["complexity"], "loc": t["loc"], "fanIn": G.nodes[f]["fanIn"]}
         for f, t in main_types.items() if not tested_by.get(f) and t["complexity"] >= 15],
        key=lambda x: -x["complexity"])
    findings["deprecated"] = [{"class": f, "loc": t["loc"], "fanIn": G.nodes[f]["fanIn"]}
                              for f, t in main_types.items() if t["deprecated"]]
    findings["packageCycles"] = cycle_pairs

    # --- use cases ----------------------------------------------------------------------------------------------
    from usecases import USE_CASES
    E = "emissary."
    UD = nx.DiGraph()  # directed, main code + wiring + config, used for hop verification
    for a, b, data in G.edges(data=True):
        UD.add_edge(a, b)
    use_cases = []
    for uc in USE_CASES:
        problems = []
        steps = []
        for fqn, note in uc["steps"]:
            if fqn not in main_types:
                problems.append(f"step class not found: {fqn}")
            steps.append({"class": fqn, "note": note})
        for i in range(len(steps) - 1):
            a, b = steps[i]["class"], steps[i + 1]["class"]
            link = {"status": "none", "path": []}
            if a in UD and b in UD:
                for x, y, label in ((a, b, "forward"), (b, a, "backward")):
                    try:
                        path = nx.shortest_path(UD, x, y)
                        if len(path) - 1 <= 3 and (link["status"] == "none" or len(path) < len(link["path"])):
                            link = {"status": "direct" if len(path) == 2 else f"{len(path) - 1} hops",
                                    "direction": label, "path": path}
                    except nx.NetworkXNoPath:
                        pass
            hubs = [n for n in link["path"][1:-1]
                    if n in main_types and (is_infra(n) or code_only.in_degree(n) >= 20 or
                                            n == "emissary.server.EmissaryServer")]
            if hubs:
                link["status"] = "via hub"
                link["hubs"] = hubs
            steps[i]["next"] = link
        seeds = [E + x for x in uc["seeds"]]
        for sd in seeds:
            if sd not in main_types:
                problems.append(f"seed not found: {sd}")
        # slice: forward 2 hops from seeds over code edges, not expanding through shared infrastructure
        members = {s_: 0 for s_ in seeds if s_ in main_types}
        members.update({st["class"]: 0 for st in steps if st["class"] in main_types})
        frontier = list(members)
        for depth in (1, 2):
            nxt = []
            for n in frontier:
                if is_infra(n) and n not in seeds:
                    continue
                for m in code_only.successors(n):
                    if m not in members:
                        members[m] = depth
                        nxt.append(m)
            frontier = nxt
        tests = sorted({tc for sd in seeds + [st["class"] for st in steps] for tc in tested_by.get(sd, ())})
        tests = sorted(set(tests) | {t for t in uc.get("tests", []) if t in test_types})
        cfg_hits = [c["file"] for c in configs.values() if pathlib.Path(c["file"]).name in uc["configs"]]
        for want in uc["configs"]:
            if not any(pathlib.Path(c["file"]).name == want for c in configs.values()) and \
                    not (repo / "src/main/config" / want).exists():
                problems.append(f"config not found: {want}")
        endpoints = [{"class": m, **ep} for m in members for ep in main_types[m]["endpoints"]]
        commands = [{"class": m, "command": main_types[m]["command"]} for m in members if main_types[m]["command"]]
        uc_places = [m for m in members if m in places]
        use_cases.append({**{k: v for k, v in uc.items() if k not in ("steps", "seeds", "configs", "tests")},
                          "steps": steps, "seeds": seeds, "members": members, "tests": tests,
                          "configs": cfg_hits, "endpoints": endpoints, "commands": commands, "places": uc_places,
                          "loc": sum(main_types[m]["loc"] for m in members), "problems": problems})
        for m in members:
            G.nodes[m].setdefault("useCases", []).append(uc["id"])

    # --- serialise -----------------------------------------------------------------------------------------------
    nodes = []
    for n, data in G.nodes(data=True):
        d = {k: v for k, v in data.items() if k not in ("annotations",) or v}
        d["id"] = n
        nodes.append(d)
    edges = [{"s": s, "t": d, "kind": data["kind"], "layer": data["layer"], **({"key": data["key"]} if "key" in data else {})}
             for s, d, data in G.edges(data=True)]
    test_classes = [{"id": f, "name": t["name"], "pkg": t["pkg"], "file": t["file"], "loc": t["loc"],
                     "doc": t["doc"], "refs": sorted({d for s, d, k in test_edges if s == f and d in main_types})}
                    for f, t in test_types.items()]
    result = {
        "meta": {"repo": str(repo), "head": subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                                                           capture_output=True, text=True).stdout.strip(),
                 "mainClasses": len(main_types), "testClasses": len(test_types),
                 "mainLoc": sum(t["loc"] for t in main_types.values()),
                 "testLoc": sum(t["loc"] for t in test_types.values()),
                 "codeEdges": len(code_edges), "configFiles": len(configs), "history": history_meta,
                 "scannedPackages": scanned, "roots": sorted(roots)},
        "nodes": nodes, "edges": edges,
        "packages": [{"id": p, **pkg_stats[p]} for p in sorted(P.nodes)],
        "packageEdges": [{"s": a, "t": b, "w": d["weight"]} for a, b, d in P.edges(data=True)],
        "sccs": sccs, "communities": communities, "places": list(places.values()),
        "configs": [{k: v for k, v in c.items()} for c in configs.values()],
        "inventory": inventory, "spi": spi, "tests": test_classes,
        "findings": findings, "useCases": use_cases,
    }
    (out / "graph.json").write_text(json.dumps(result, indent=1, default=list))
    nx.write_graphml(nx.DiGraph([(e["s"], e["t"]) for e in edges]), out / "graph.graphml")
    print(json.dumps(result["meta"], indent=1))
    print({k: len(v) for k, v in findings.items()})
    for uc in use_cases:
        links = [st.get("next", {}).get("status") for st in uc["steps"][:-1]]
        print(f"  {uc['id']:15s} members={len(uc['members']):3d} tests={len(uc['tests']):3d} "
              f"links={links} problems={uc['problems']}")
    print("places:", len(places), "sccs:", [len(s) for s in sccs], "communities:", len(communities))


if __name__ == "__main__":
    main()
