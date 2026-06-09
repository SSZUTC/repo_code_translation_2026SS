#!/bin/bash
# Run all public tests for ali-bouali_one-to-one-chat-spring-boot-web-socket

set -e

./mvnw -Dtest='*PublicTest' test