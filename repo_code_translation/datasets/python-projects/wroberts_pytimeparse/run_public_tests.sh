#!/bin/bash
echo "Installing test dependencies for public tests..."
pip install pytest > /dev/null
echo "Running public pytest tests in ./public_tests/ ..."
pytest ./public_tests/