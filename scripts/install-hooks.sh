#!/usr/bin/env bash
# Install git hooks for the Collaboration Guardian.
# Run once per developer: bash scripts/install-hooks.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Installing Collaboration Guardian git hooks..."

# Point git to our custom hooks directory
git -C "$REPO_ROOT" config core.hooksPath .githooks

# Ensure the pre-push hook is executable
chmod +x "$REPO_ROOT/.githooks/pre-push"

echo "Done. Pre-push hook is now active."
echo "To bypass (emergency): git push --no-verify"
