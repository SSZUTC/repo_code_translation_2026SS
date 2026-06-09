#!/bin/bash
set -e

# Install dependencies if requirements file exists
if [ -f requirements.txt ]; then
    pip install -r requirements.txt
fi

# Install pytest & coverage
pip install pytest pytest-cov coverage

# Run all tests (including legacy and new ones)
pytest --cov=fuzzywuzzy --cov-branch --cov-report=term-missing --cov-report=html test_fuzzywuzzy.py test_fuzzywuzzy_pytest.py test_fuzzywuzzy_hypothesis.py tests/