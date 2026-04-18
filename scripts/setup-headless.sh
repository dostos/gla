#!/bin/bash
# Install Xvfb if not present, build everything with Bazel
set -e

echo "=== OpenGPA Headless Setup ==="

# Check/install Xvfb
if ! command -v Xvfb &> /dev/null; then
    echo "Installing Xvfb..."
    sudo apt-get update && sudo apt-get install -y xvfb
fi

# Check/install GL libraries
if ! dpkg -l | grep -q libgl1-mesa-dev; then
    echo "Installing Mesa GL..."
    sudo apt-get install -y libgl1-mesa-dev libx11-dev
fi

# Build everything
echo "Building OpenGPA..."
bazel build //...

# Install Python deps
pip install fastapi uvicorn requests

echo "=== Setup complete ==="
echo "Run: ./scripts/start-eval-server.sh"
