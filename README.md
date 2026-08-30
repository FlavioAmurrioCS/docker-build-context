# docker-build-context

List the files Docker sends to the daemon as a build context.

A large build context makes every build slow and can leak files you never meant
to send. `.dockerignore` controls what gets sent, but its matching rules are
subtle, and nothing in the Docker CLI shows you the result. This tool does.

```console
$ docker-build-context ls --summary
Dockerfile
go.mod
main.go
included: 3 files, 4.2 KiB
```

## Why another one

The `.dockerignore` rules are easy to reimplement almost correctly. This tool
does not reimplement them. It calls the libraries Docker and BuildKit call:

| Step | Package |
| --- | --- |
| Parse the ignore file | `github.com/moby/patternmatcher/ignorefile` |
| Match paths | `github.com/moby/patternmatcher` |
| Walk and filter the tree | `github.com/tonistiigi/fsutil` |

`fsutil` is what BuildKit's own `llb.ExcludePatterns` uses to send a build
context, so the traversal, the parent-directory match propagation and the
subtree-skipping optimization are the real ones rather than a copy.

CI checks this rather than asserting it. For every fixture, `scripts/conformance.sh`
builds `FROM scratch` with `COPY . /`, exports the image as a tarball, and diffs
the tar members against this tool's output.

## Install

```console
$ uvx docker-build-context ls          # no install
$ pipx run docker-build-context ls     # no install
$ uv tool install docker-build-context
$ pip install docker-build-context
```

Prebuilt binaries for Linux, macOS and Windows are attached to each
[release](https://github.com/FlavioAmurrioCS/docker-build-context/releases).
With a Go toolchain:

```console
$ go install github.com/FlavioAmurrioCS/docker-build-context/cmd/docker-build-context@latest
```

The tool reads the filesystem. It doesn't need a Docker installation or a
running daemon.

## Usage

```
docker-build-context ls [PATH] [flags]         list context files
docker-build-context explain PATH [flags]      show which rule decided a path
docker-build-context install-docker-plugin     register as "docker buildcontext"
docker-build-context version
```

`ls` prints the files Docker sends. Flags:

| Flag | Effect |
| --- | --- |
| `-f`, `--file` | Dockerfile name, which also selects `<name>.dockerignore` |
| `--ignored` | list the excluded files instead |
| `--all` | list everything, prefixed `+` for sent and `-` for excluded |
| `--size` | prefix each path with its size in bytes |
| `--summary` | print totals to stderr after the listing |
| `--json` | emit the full result as JSON |
| `-0` | separate paths with NUL, for `xargs -0` |

Find what is filling a context:

```console
$ docker-build-context ls --size | sort -rn | head
```

Ask why one path is where it is:

```console
$ docker-build-context explain node_modules/keep/index.js
node_modules/keep/index.js: included
  .dockerignore:1        node_modules             ignored
  .dockerignore:2        !node_modules/keep       re-included  (decisive)
```

### As a Docker CLI plugin

```console
$ docker-build-context install-docker-plugin
$ docker buildcontext ls
```

This symlinks the binary into `~/.docker/cli-plugins/`. Use `--system` to
install it for every user instead.

The subcommand is `buildcontext` with no hyphen because Docker validates plugin
names against `^[a-z][a-z0-9]*$` and refuses to load anything else.

Python wheels cannot do this at install time. Wheels have no post-install hook,
and `~/.docker/cli-plugins/` sits outside every Python install path, so the step
is an explicit command.

## Python API

The wheel bundles the binary and a typed wrapper.

```python
from docker_build_context import explain
from docker_build_context import ls

result = ls(".", mode="all")
print(result.summary.included.files, result.summary.included.size)

for entry in result.entries:
    if entry.status == "ignored":
        print(entry.path, "ignored by", f"{result.ignorefile}:{entry.rule_line}")

print(explain("node_modules/keep/index.js").rules[-1])
```

The binary installs into the environment's scripts directory, so
`docker-build-context` is on PATH after a `pip install`, and the Python wrapper
doesn't add interpreter startup to the command itself.

## JSON output

`--json` emits a versioned document. Check `schema` before reading it.

```json
{
  "schema": 1,
  "context": "/home/me/project",
  "dockerfile": "Dockerfile",
  "ignorefile": ".dockerignore",
  "summary": {
    "included": { "files": 120, "bytes": 4823901 },
    "ignored": { "files": 4210, "bytes": 831299122 }
  },
  "entries": [
    { "path": "main.go", "status": "included", "size": 1234 },
    {
      "path": "node_modules",
      "status": "included",
      "size": 0,
      "dir": true,
      "materialized": true,
      "rule": "node_modules",
      "rule_line": 1
    }
  ],
  "warnings": []
}
```

Notes on `summary.ignored` and `materialized`.

`summary.ignored` is `null` in the default mode. Ignored directories are skipped
without being read when no rule can re-include anything inside them, so no
complete total exists. Pass `--all` or `--ignored` to get one.

`materialized` marks a directory that a rule matched but that Docker still
sends, because a negated rule rescued something inside it and the directory has
to exist to hold it. Docker's own context tarball contains these, so the listing
does too.

## Ignore file resolution

BuildKit looks for `<dockerfile>.dockerignore` first, then `.dockerignore` in
the context directory. When no `-f` is given and no `Dockerfile` exists, the
lowercase `dockerfile` is also accepted. This tool follows the same order.

One difference from `docker build` is worth knowing. The Docker CLI keeps the
Dockerfile and `.dockerignore` in the tarball it transmits even when the ignore
file excludes them, and the daemon drops them afterwards. This tool reports the
context you end up with, so it shows them as excluded.

## Development

`mise.toml` defines the tools and the tasks.

```console
$ mise run build        # compile the binary
$ mise run test         # go test + pytest
$ mise run lint         # pre-commit across the repo
$ mise run conformance  # diff against real docker build output
$ mise run wheels       # build all platform wheels
$ mise run test-clone   # verify a fresh clone in a container
```

## License

MIT. See [LICENSE](LICENSE).

`src/docker_build_context/_find.py` adapts the binary-discovery search order
from [uv](https://github.com/astral-sh/uv), which is MIT OR Apache-2.0.
