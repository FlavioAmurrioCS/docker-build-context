"""List the files Docker sends to the daemon as a build context.

This package bundles the ``docker-build-context`` binary and wraps its JSON
output in typed dataclasses. The heavy lifting stays in Go, which calls the
same libraries BuildKit does, so results match ``docker build`` exactly.

    >>> from docker_build_context import ls
    >>> result = ls(".")
    >>> result.summary.included.files > 0
    True
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal

from docker_build_context._find import BINARY_ENV_VAR
from docker_build_context._find import BINARY_NAME
from docker_build_context._find import BinaryNotFoundError
from docker_build_context._find import find_binary

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "BINARY_ENV_VAR",
    "BINARY_NAME",
    "SCHEMA_VERSION",
    "BinaryNotFoundError",
    "Counts",
    "Entry",
    "Explanation",
    "MatchedRule",
    "Result",
    "Summary",
    "explain",
    "find_binary",
    "ls",
]

# The JSON schema version this wrapper understands. The binary stamps every
# document with "schema"; a mismatch means the two halves are out of step.
SCHEMA_VERSION = 1

Status = Literal["included", "ignored"]
Mode = Literal["included", "ignored", "all"]


@dataclass(frozen=True)
class Counts:
    """A file and byte tally. Directories count towards neither."""

    files: int
    size: int


@dataclass(frozen=True)
class Summary:
    """Totals for both sides of a walk.

    ``ignored`` is ``None`` in the default mode, where ignored directories are
    skipped wholesale and no complete total exists.
    """

    included: Counts
    ignored: Counts | None


@dataclass(frozen=True)
class Entry:
    """One path in the build context."""

    path: str
    status: Status
    size: int
    is_dir: bool = False
    #: A directory an ignore rule matched that Docker still sends, because a
    #: negated rule re-included something inside it.
    materialized: bool = False
    rule: str | None = None
    rule_line: int | None = None
    negated: bool = False


@dataclass(frozen=True)
class Result:
    """The full result of listing a build context."""

    schema: int
    context: str
    dockerfile: str
    ignorefile: str
    summary: Summary
    entries: tuple[Entry, ...]
    warnings: tuple[str, ...] = ()

    def paths(self) -> tuple[str, ...]:
        """Return just the paths, in the order the binary reported them."""
        return tuple(entry.path for entry in self.entries)


@dataclass(frozen=True)
class MatchedRule:
    """An ignore-file rule that applies to an explained path."""

    rule: str
    line: int
    negated: bool
    #: The last matching rule, which determines the outcome.
    decisive: bool


@dataclass(frozen=True)
class Explanation:
    """Why a single path is included or ignored."""

    schema: int
    context: str
    dockerfile: str
    ignorefile: str
    path: str
    status: Status
    exists: bool
    rules: tuple[MatchedRule, ...]


def ls(
    path: str = ".",
    *,
    dockerfile: str | None = None,
    mode: Mode = "included",
) -> Result:
    """List the build context at ``path``.

    Args:
        path: the build context directory.
        dockerfile: the ``-f`` value, used to find ``<name>.dockerignore``.
        mode: ``included`` (what Docker sends), ``ignored``, or ``all``.

    Returns:
        The parsed result.
    """
    args = ["ls", "--json"]
    if mode == "ignored":
        args.append("--ignored")
    elif mode == "all":
        args.append("--all")
    if dockerfile is not None:
        args += ["-f", dockerfile]
    args.append(path)
    return _parse_result(_run(args))


def explain(
    target: str,
    *,
    path: str = ".",
    dockerfile: str | None = None,
) -> Explanation:
    """Report which ignore-file rule decided ``target``.

    Args:
        target: the path to explain, relative to the context or absolute.
            It need not exist.
        path: the build context directory.
        dockerfile: the ``-f`` value, used to find ``<name>.dockerignore``.

    Returns:
        The parsed explanation.
    """
    args = ["explain", "--json", "-C", path]
    if dockerfile is not None:
        args += ["-f", dockerfile]
    args.append(target)
    return _parse_explanation(_run(args))


def _run(args: Sequence[str]) -> dict[str, Any]:
    binary = find_binary()
    proc = subprocess.run(  # noqa: S603
        [binary, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        msg = f"{BINARY_NAME} {' '.join(args)} failed: {proc.stderr.strip()}"
        raise RuntimeError(msg)
    data: dict[str, Any] = json.loads(proc.stdout)
    _check_schema(data)
    return data


def _check_schema(data: dict[str, Any]) -> None:
    schema = data.get("schema")
    if schema != SCHEMA_VERSION:
        msg = (
            f"{BINARY_NAME} emitted schema {schema!r}, but this package understands "
            f"{SCHEMA_VERSION}. The binary and the Python wrapper are out of step."
        )
        raise RuntimeError(msg)


def _counts(data: dict[str, Any] | None) -> Counts | None:
    if data is None:
        return None
    return Counts(files=data["files"], size=data["bytes"])


def _parse_result(data: dict[str, Any]) -> Result:
    included = _counts(data["summary"]["included"])
    assert included is not None  # noqa: S101 - the binary always reports this side
    return Result(
        schema=data["schema"],
        context=data["context"],
        dockerfile=data["dockerfile"],
        ignorefile=data["ignorefile"],
        summary=Summary(included=included, ignored=_counts(data["summary"]["ignored"])),
        entries=tuple(
            Entry(
                path=e["path"],
                status=e["status"],
                size=e["size"],
                is_dir=e.get("dir", False),
                materialized=e.get("materialized", False),
                rule=e.get("rule"),
                rule_line=e.get("rule_line"),
                negated=e.get("negated", False),
            )
            for e in data["entries"]
        ),
        warnings=tuple(data.get("warnings") or ()),
    )


def _parse_explanation(data: dict[str, Any]) -> Explanation:
    return Explanation(
        schema=data["schema"],
        context=data["context"],
        dockerfile=data["dockerfile"],
        ignorefile=data["ignorefile"],
        path=data["path"],
        status=data["status"],
        exists=data["exists"],
        rules=tuple(
            MatchedRule(
                rule=r["rule"],
                line=r["line"],
                negated=r["negated"],
                decisive=r["decisive"],
            )
            for r in data["rules"]
        ),
    )
