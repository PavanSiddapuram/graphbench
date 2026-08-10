#!/usr/bin/env bash
# Installs .githooks/pre-commit into .git/hooks/pre-commit. .git/hooks is
# never tracked by git, so this script is what makes the hook reproducible
# for anyone who clones the repo - see CLAUDE.md's "gitleaks pre-commit
# hook, installed and verified to actually block" requirement.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cp "$repo_root/.githooks/pre-commit" "$repo_root/.git/hooks/pre-commit"
chmod +x "$repo_root/.git/hooks/pre-commit"
echo "installed $repo_root/.git/hooks/pre-commit"
