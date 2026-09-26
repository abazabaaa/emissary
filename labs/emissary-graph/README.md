# emissary-graph

Builds a multi-layer graph of the Emissary codebase and an interactive explorer page. It lives outside the repo on purpose.

## Layers
- **code**: tree-sitter Java ASTs (extends, implements, new, type use, class-name string literals as "reflect")
- **wiring**: Jersey `packages(...)` scanning in `EmissaryServer`, `META-INF/services`
- **config**: every `.cfg` (class names in values, `places*.cfg` deployments resolved via `ClassNameInventory`, place routing keys), plus logback/properties/templates and the `emissary` launcher
- **tests**: which test classes reference each main class
- **history**: per-file commit counts from a blob-less clone of the upstream repo

## Run
```
python3 -m venv venv && venv/bin/pip install tree-sitter tree-sitter-java networkx
git clone --bare --filter=blob:none https://github.com/NationalSecurityAgency/emissary.git history/emissary.git
venv/bin/python analyze.py --repo /path/to/emissary --history history/emissary.git --out out
venv/bin/python build_page.py          # -> out/explorer.html
```
Outputs: `out/graph.json` (everything), `out/graph.graphml` (for Gephi/yEd), `out/explorer.html`.

## Use cases
`usecases.py` holds hand-written flows. Each step must name a real class; the analyzer reports every hop between
steps as a direct reference, an n-hop path, "via hub" (only connected through a widely used class, so weak evidence),
or no static link (HTTP, config, or sibling components). Add or edit use cases there and re-run.

## Limits
- Classes named only in a deployment's own config are invisible, so "unreferenced" is not "dead".
- Method-level call graphs are out of scope. JavaParser with its symbol solver would be the next step.
- Complexity is a branch count per class, not per method.
