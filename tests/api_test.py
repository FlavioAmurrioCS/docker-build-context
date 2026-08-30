from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from docker_build_context import SCHEMA_VERSION
from docker_build_context import explain
from docker_build_context import ls

if TYPE_CHECKING:
    from pathlib import Path


def test_ls_returns_the_included_set(fixture_dir: Path) -> None:
    result = ls(str(fixture_dir / "pycache" / "context"))
    assert result.schema == SCHEMA_VERSION
    assert result.ignorefile == ".dockerignore"
    assert "a/b/keep.py" in result.paths()
    # The bug that motivated the project: a "**/__pycache__" rule has to reach
    # paths nested deeper than the pattern itself.
    assert not [p for p in result.paths() if "__pycache__" in p]


def test_ls_default_mode_reports_no_ignored_total(fixture_dir: Path) -> None:
    # Ignored directories are skipped without being read, so there is no
    # honest total to report.
    result = ls(str(fixture_dir / "pycache" / "context"))
    assert result.summary.ignored is None
    assert result.summary.included.files > 0


def test_ls_all_mode_counts_both_sides(fixture_dir: Path) -> None:
    result = ls(str(fixture_dir / "reinclude" / "context"), mode="all")
    assert result.summary.ignored is not None
    assert result.summary.ignored.files == 1
    assert result.summary.included.files == 4


def test_ls_ignored_mode(fixture_dir: Path) -> None:
    result = ls(str(fixture_dir / "reinclude" / "context"), mode="ignored")
    assert result.paths() == ("node_modules/drop", "node_modules/drop/index.js")


def test_materialized_directory_is_reported(fixture_dir: Path) -> None:
    result = ls(str(fixture_dir / "reinclude" / "context"), mode="all")
    entry = next(e for e in result.entries if e.path == "node_modules")
    assert entry.status == "included"
    assert entry.materialized
    assert entry.is_dir
    assert entry.rule == "node_modules"
    assert entry.rule_line == 1


def test_dockerfile_selects_the_ignore_file(fixture_dir: Path) -> None:
    context = str(fixture_dir / "perdockerfile" / "context")
    result = ls(context, dockerfile="Prj1")
    assert result.ignorefile == "Prj1.dockerignore"
    assert "only-prj1" not in result.paths()
    assert "only-default" in result.paths()


def test_explain_names_the_decisive_rule(fixture_dir: Path) -> None:
    result = explain(
        "node_modules/keep/index.js",
        path=str(fixture_dir / "reinclude" / "context"),
    )
    assert result.status == "included"
    assert result.exists
    assert [r.rule for r in result.rules] == ["node_modules", "!node_modules/keep"]
    assert result.rules[-1].decisive
    assert result.rules[-1].line == 2


def test_explain_accepts_a_path_that_does_not_exist(fixture_dir: Path) -> None:
    result = explain(
        "node_modules/nothing/here.js",
        path=str(fixture_dir / "reinclude" / "context"),
    )
    assert not result.exists
    assert result.status == "ignored"


def test_errors_carry_the_binary_message(fixture_dir: Path) -> None:
    with pytest.raises(RuntimeError, match="outside the build context"):
        explain("../escape", path=str(fixture_dir / "none" / "context"))
