#!/usr/bin/env bash
# Builds and runs the firmware's pure-C++ tests on your laptop (needs g++ or clang++).
set -euo pipefail
cd "$(dirname "$0")"
CXX="${CXX:-c++}"
"$CXX" -std=c++17 -Wall -Wextra -O1 -fsanitize=address,undefined -o /tmp/tro_tap_tests test_tap_detector.cpp
/tmp/tro_tap_tests
