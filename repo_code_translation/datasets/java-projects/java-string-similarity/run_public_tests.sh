#!/bin/bash
set -e
# Run all public tests using Maven, scanning only the public test tree
mvn -Dtest='*PublicTest' test -DfailIfNoTests=false -f ./pom.xml -DtestSourceDirectory=src/test_public/java