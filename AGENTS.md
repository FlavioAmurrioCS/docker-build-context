# AGENTS.md

Conventions for coding agents working in this repo.

This is a Go CLI that lists the files Docker sends as a build context, distributed
as Python wheels and as a Docker CLI plugin. The Python half is a thin typed
wrapper around the binary.

## Hard rules

1. **Never reimplement `.dockerignore` semantics.** The whole point of this
   project is that it calls the same libraries Docker and BuildKit call:
   `moby/patternmatcher/ignorefile` to parse, `moby/patternmatcher` to match,
   and `tonistiigi/fsutil` for traversal. If you find yourself writing a
   pattern matcher, stop. A hand-rolled matcher is what the JavaScript prior
   art did, and it is why we can claim something it cannot.

2. **`scripts/conformance.sh` is the source of truth.** It builds each fixture
   with `FROM scratch` and `COPY . /`, exports the image as a tarball, and
   diffs the members against our listing. When it disagrees with a unit test,
   the unit test is wrong. It found the `materialized` directory behaviour that
   every other check missed. Run it after any change to matching or walking.

3. **Never run `git push`.** That decision belongs to a human, every time.

4. **Suggest the commit and wait.** One logical change per commit, named so
   `git log --oneline` reads as a history. Do not commit on your own
   initiative.

5. **Never run `python-cookie/update.py` against this repo.** The template sync
   overwrites everything except `tests/`, `*.py`, `LICENSE` and `README`, which
   here means it would destroy `pyproject.toml` (the Go build hook and the
   sdist include list), `.pre-commit-config.yaml` (the Go, shell and vale
   hooks) and `.github/workflows/main.yaml` (the wheel matrix). This repo has
   deliberately left the template fleet.

## Correctness invariants

Read these before changing `internal/dctx/`:

- `ignorefile.go` resolves `<dockerfile>.dockerignore` then `.dockerignore`,
  matching `buildkit/frontend/dockerui/config.go`. It recovers line numbers by
  replaying only ReadAll's comment and blank-line skipping. It does not
  duplicate any pattern normalization.
- `walk.go` threads each directory's `patternmatcher.MatchInfo` to its children
  the way `fsutil`'s `filterFS.Walk` does, and settles a directory's fate when
  it pops rather than when it is visited. That deferral is what produces
  `materialized`.
- `match.go` reports which rule decided a path by testing each rule alone and
  taking the last match. `TestAttributionAgreesWithMatcher` is the safety net
  under that shortcut; if it fails, the shortcut is no longer valid and the
  attribution has to change, not the test.

## Schema decisions worth keeping

`summary.ignored` is `null` in the default mode, because ignored directories
are skipped without being read and no complete total exists. Do not paper over
this with an undercount.

`materialized` marks a directory an ignore rule matched that Docker still
sends, because a negated rule rescued something inside it. Docker's tarball
contains these, so the listing does too.

Bump `SchemaVersion` in `walk.go` and `SCHEMA_VERSION` in
`src/docker_build_context/__init__.py` together. The Python wrapper refuses a
document it does not recognise.

## Tooling

mise owns tools and tasks.

```sh
mise run build        # compile into ./build
mise run test         # go test + pytest
mise run lint         # pre-commit across the repo
mise run conformance  # diff against real docker build output
mise run wheels       # every platform wheel into ./dist
mise run test-clone   # verify a fresh clone in a Debian container
```

Shell scripts start with `eval "$(mise env -s bash)"`, because `mise activate`
is a prompt hook that never fires in a non-interactive shell. They must pass
`shellcheck` and `shfmt -i 2 -ci`. No `mapfile`: macOS still has bash 3.2.

Run `mise run test-clone` after touching `mise.toml`, `pyproject.toml`,
`hatch_build.py`, `.pre-commit-config.yaml` or anything in `scripts/`. A temp
directory on the development machine inherits a working Go toolchain, a warm
module cache and an existing uv, and hides the failures that matter.

## Packaging

The wheel holds the Go binary in `.data/scripts` and the Python package beside
it, which is the layout `uv` uses. There is deliberately no `[project.scripts]`
entry: a `console_scripts` shim would add interpreter startup to every
invocation, and this runs under pre-commit.

`hatch_build.py` builds one target per invocation, chosen by `DBC_TARGET` and
defaulting to the host so a plain `uv build` works. Version comes from git tags
through hatch-vcs and reaches the binary through `-X main.version`.

The distribution name, the binary name and the repo name are all
`docker-build-context`. That is what makes `uvx docker-build-context` and
`pipx run docker-build-context` work without configuration. Do not add a short
alias.

The Docker plugin subcommand is `buildcontext` with no hyphen, because Docker
validates plugin names against `^[a-z][a-z0-9]*$` and refuses anything else.
This is checked by `TestPluginBinaryNameMatchesDockersRule`.

## Prose is linted

`vale-ai-tells` runs on changed markdown in pre-commit and on commit messages
via the `commit-msg` hook. `mise run prose` lints everything. The style packs
are gitignored, and `scripts/prose-lint.sh` fetches them on first run.

## Writing style

Write for someone debugging a slow build at 2am.

- Say what a thing is for in the first line.
- Record the gotcha. The comment explaining why `Matches` is not
  `MatchesOrParentMatches` is worth more than the code around it.
- Cite upstream when a behaviour is inherited: file and line, so the next
  reader can check it still holds.
- An empty section beats filler.
