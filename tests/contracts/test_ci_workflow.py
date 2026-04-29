from __future__ import annotations

from pathlib import Path


def test_tests_workflow_enforces_documented_ci_gates() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workflow = repo_root / ".github" / "workflows" / "tests.yml"

    assert workflow.is_file()
    text = workflow.read_text(encoding="utf-8")

    for command in (
        "uv sync --locked --group dev",
        "uv run ruff format --check",
        "uv run ruff check",
        "uv run ty check",
        "uv run pytest",
    ):
        assert command in text

    assert "# " + "type: ignore" in text
    assert "# " + "ty: ignore" in text
