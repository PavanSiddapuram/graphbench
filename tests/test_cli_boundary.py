"""Guards CLAUDE.md's prime-directive corollary: FakeAdapter must be
impossible for cli.py to select. This is checked by scanning cli.py's
actual source text, not by trusting a docstring - a docstring can drift,
an import statement is what actually makes something reachable.
"""

from pathlib import Path

CLI_SOURCE = Path("cli.py").read_text()


def test_cli_never_imports_tests_package() -> None:
    assert "tests" not in CLI_SOURCE.split(), "cli.py must never import from tests/ (see FakeAdapter)"
    assert "import tests" not in CLI_SOURCE
    assert "from tests" not in CLI_SOURCE


def test_cli_never_names_fake_adapter() -> None:
    assert "FakeAdapter" not in CLI_SOURCE


def test_build_adapter_only_constructs_real_adapter_classes() -> None:
    for real_adapter in ("BoltAdapter", "FalkorDBAdapter", "ArangoDBAdapter"):
        assert real_adapter in CLI_SOURCE
