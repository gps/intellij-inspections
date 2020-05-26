#!/bin/sh

set -eu

/opt/idea/bin/inspect.sh ${GITHUB_WORKSPACE}/build.gradle ${GITHUB_WORKSPACE}/${INPUT_INSPECTIONS_FILE} ${GITHUB_WORKSPACE}/target/idea_inspections -v2

echo "GITHUB_EVENT_PATH: ${GITHUB_EVENT_PATH}"
echo "GITHUB_REF: ${GITHUB_REF}"

/analyze_inspections.py -i ${GITHUB_WORKSPACE}/target/idea_inspections
