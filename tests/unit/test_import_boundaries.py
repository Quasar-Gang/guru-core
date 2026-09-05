"""The layering rules are enforced by tooling, so the test suite runs the tooling."""

import subprocess


def test_import_linter_contracts_pass():
    result = subprocess.run(["uv", "run", "lint-imports"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
