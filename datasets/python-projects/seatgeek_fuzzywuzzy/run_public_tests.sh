#!/bin/bash
# Ensure that the fuzzywuzzy package is discoverable
export PYTHONPATH=$(pwd):$PYTHONPATH

pip install -q pytest hypothesis
pytest public_tests/