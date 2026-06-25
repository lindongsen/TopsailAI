#!/bin/bash

[ -n "$1" ] && {
    echo "ERROR: Current script is only suitable for running all tests, not for executing individual tests"
    exit 1
}

CWD=$(dirname $(readlink -f "$0"))
cd "${CWD}"

find . | grep "/test_" | grep -E '\.py$' | xargs -i bash -c "pytest {} >/dev/null 2>&1 || echo Failed:{}"
