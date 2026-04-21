#!/bin/bash

CWD=$(dirname $(readlink -f "$0"))
cd "${CWD}"

find . | grep "/test_" | grep -E '\.py$' | xargs -i bash -c "pytest {} >/dev/null 2>&1 || echo Failed:{}"

