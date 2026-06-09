#!/bin/bash
echo "Installing test dependencies..."
pip install pytest coverage pytest-cov > /dev/null
echo "Running pytest with coverage analysis..."
coverage run --branch -m pytest