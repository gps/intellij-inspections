#!/bin/sh

set -eu

/jb/idea/bin/inspect.sh ${GITHUB_WORKSPACE}/build.gradle ${GITHUB_WORKSPACE}/${INPUT_INSPECTIONS_FILE} ${GITHUB_WORKSPACE}/target/idea_inspections -v2

/analyze_inspections.py -i ${GITHUB_WORKSPACE}/target/idea_inspections
