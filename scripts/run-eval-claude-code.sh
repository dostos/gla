#!/bin/bash
# Runs the eval harness using Claude Code subagents
# Prerequisites: OpenGPA eval server running, scenarios captured
set -e

echo "=== OpenGPA Eval via Claude Code ==="
echo "This script captures all scenarios and then provides"
echo "instructions for running the eval in Claude Code."
echo ""

# Capture all scenarios
./scripts/capture-all-scenarios.sh

echo ""
echo "========================================="
echo "Scenarios captured. To run the eval:"
echo ""
echo "1. Open Claude Code in this repo"
echo "2. The .mcp.json config auto-loads OpenGPA tools"
echo "3. Ask Claude Code to debug each scenario:"
echo ""
echo '   "Debug the rendering bug in tests/eval/e1_state_leak.c'
echo '    using the OpenGPA tools. The app should show two differently'
echo '    colored quads but both appear the same color."'
echo ""
echo "Or run all at once:"
echo '   "For each scenario in tests/eval/*.md, read the problem'
echo '    description and use OpenGPA tools to diagnose the bug.'
echo '    Report your findings for each."'
echo "========================================="
