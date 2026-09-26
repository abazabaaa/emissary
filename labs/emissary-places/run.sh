#!/usr/bin/env bash
# Start a standalone Emissary node with the demo places.
#   JAVA=/path/to/java ./run.sh      use a different JDK (e.g. GraalVM) for the node and the Tika forks
#   AGENTS=8 ./run.sh                agent pool size
#   EXTRA_JAVA_OPTS="-D..." ./run.sh extra JVM options for the node
# Input:  ./target/data/InputData      Output: ./build/localoutput/json
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
JAVA="${JAVA:-java}"
AGENTS="${AGENTS:-4}"

"$HERE/setup-config.sh" >/dev/null
if [ ! -f target/classes/demo/places/TikaIdPlace.class ] || [ ! -f cp.txt ]; then
  mvn -q -B compile dependency:build-classpath -Dmdep.outputFile=cp.txt -Dmdep.includeScope=runtime
fi

export PROJECT_BASE="$HERE/build"
mkdir -p target/data/InputData
exec "$JAVA" -Xmx2g -Ddemo.tika.javaPath="$JAVA" ${EXTRA_JAVA_OPTS:-} \
  -cp "target/classes:$(cat cp.txt)" emissary.Emissary \
  server -m standalone -a "$AGENTS" -b "$PROJECT_BASE" -c "$PROJECT_BASE/config"
