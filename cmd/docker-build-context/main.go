// Command docker-build-context lists the files Docker sends to the daemon as a
// build context.
//
// The same binary doubles as a Docker CLI plugin: install it into a
// cli-plugins directory and it answers as "docker build-context".
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/FlavioAmurrioCS/docker-build-context/dctx"
)

// version is overwritten at build time with -X main.version=...
var version = "dev"

// errUsage makes a command exit 2 instead of 1.
var errUsage = errors.New("usage")

func main() {
	if err := run(os.Args[1:], os.Stdout, os.Stderr); err != nil {
		if errors.Is(err, errUsage) {
			os.Exit(2)
		}
		fmt.Fprintln(os.Stderr, "docker-build-context:", err)
		os.Exit(1)
	}
}

func run(args []string, stdout, stderr io.Writer) error {
	// Docker hands plugins the whole original argv, global flags and all.
	if stripped, ok := dctx.StripPluginPrefix(args); ok {
		args = stripped
	}

	if len(args) == 0 {
		usage(stderr)
		return errUsage
	}

	cmd, rest := args[0], args[1:]
	switch cmd {
	case "ls":
		return cmdLs(rest, stdout, stderr)
	case "explain":
		return cmdExplain(rest, stdout, stderr)
	case "install-docker-plugin":
		return cmdInstallPlugin(rest, stdout, stderr)
	case "version", "--version", "-v":
		fmt.Fprintln(stdout, version)
		return nil
	case dctx.MetadataSubcommand:
		return dctx.WritePluginMetadata(stdout, version)
	case "help", "--help", "-h":
		usage(stdout)
		return nil
	default:
		fmt.Fprintf(stderr, "unknown command %q\n\n", cmd)
		usage(stderr)
		return errUsage
	}
}

func usage(w io.Writer) {
	fmt.Fprint(w, `docker-build-context - list the files Docker sends as the build context

usage:
  docker-build-context ls [PATH] [flags]         list context files
  docker-build-context explain PATH [flags]      show which rule decided a path
  docker-build-context install-docker-plugin     register as "docker build-context"
  docker-build-context version

run a subcommand with --help for its flags
`)
}

// newFlagSet builds a flag set that reports errors to us rather than exiting.
func newFlagSet(name string, stderr io.Writer) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(stderr)
	return fs
}

func cmdLs(args []string, stdout, stderr io.Writer) error {
	fs := newFlagSet("ls", stderr)
	dockerfile := fs.String("f", "", "`name` of the Dockerfile, used to find <name>.dockerignore")
	fs.StringVar(dockerfile, "file", "", "alias for -f")
	ignored := fs.Bool("ignored", false, "list excluded files instead of included ones")
	all := fs.Bool("all", false, "list every file, prefixed with + (included) or - (ignored)")
	sizes := fs.Bool("size", false, "prefix each path with its size in bytes")
	asJSON := fs.Bool("json", false, "emit the full result as JSON")
	nulSep := fs.Bool("0", false, "separate paths with NUL instead of newline, for xargs -0")
	summary := fs.Bool("summary", false, "print totals to stderr after the listing")
	if err := fs.Parse(args); err != nil {
		return errUsage
	}

	if *ignored && *all {
		fmt.Fprintln(stderr, "-ignored and -all are mutually exclusive")
		return errUsage
	}
	if fs.NArg() > 1 {
		fmt.Fprintln(stderr, "expected at most one PATH")
		return errUsage
	}

	dir := "."
	if fs.NArg() == 1 {
		dir = fs.Arg(0)
	}

	mode := dctx.ModeIncluded
	switch {
	case *all:
		mode = dctx.ModeAll
	case *ignored:
		mode = dctx.ModeIgnored
	}

	res, err := dctx.Walk(context.Background(), dctx.Options{
		Context:    dir,
		Dockerfile: *dockerfile,
		Mode:       mode,
	})
	if err != nil {
		return err
	}

	for _, w := range res.Warnings {
		fmt.Fprintln(stderr, "warning:", w)
	}

	if *asJSON {
		enc := json.NewEncoder(stdout)
		enc.SetIndent("", "  ")
		return enc.Encode(res)
	}

	sep := "\n"
	if *nulSep {
		sep = "\x00"
	}
	for _, e := range res.Entries {
		var b strings.Builder
		if *all {
			if e.Status == dctx.StatusIncluded {
				b.WriteString("+ ")
			} else {
				b.WriteString("- ")
			}
		}
		if *sizes {
			fmt.Fprintf(&b, "%10d  ", e.Size)
		}
		b.WriteString(e.Path)
		b.WriteString(sep)
		if _, err := io.WriteString(stdout, b.String()); err != nil {
			return err
		}
	}

	if *summary {
		printSummary(stderr, res)
	}
	return nil
}

func printSummary(w io.Writer, res *dctx.Result) {
	fmt.Fprintf(w, "included: %s, %s\n",
		plural(res.Summary.Included.Files, "file"), humanBytes(res.Summary.Included.Bytes))
	if res.Summary.Ignored != nil {
		fmt.Fprintf(w, "ignored:  %s, %s\n",
			plural(res.Summary.Ignored.Files, "file"), humanBytes(res.Summary.Ignored.Bytes))
	} else {
		fmt.Fprintln(w, "ignored:  not counted (ignored directories were skipped; use -all)")
	}
}

func plural(n int64, noun string) string {
	if n == 1 {
		return fmt.Sprintf("%d %s", n, noun)
	}
	return fmt.Sprintf("%d %ss", n, noun)
}

func humanBytes(n int64) string {
	const unit = 1024
	if n < unit {
		return fmt.Sprintf("%d B", n)
	}
	div, exp := int64(unit), 0
	for v := n / unit; v >= unit; v /= unit {
		div *= unit
		exp++
	}
	return fmt.Sprintf("%.1f %ciB", float64(n)/float64(div), "KMGTPE"[exp])
}

func cmdExplain(args []string, stdout, stderr io.Writer) error {
	fs := newFlagSet("explain", stderr)
	dockerfile := fs.String("f", "", "`name` of the Dockerfile, used to find <name>.dockerignore")
	fs.StringVar(dockerfile, "file", "", "alias for -f")
	dir := fs.String("C", ".", "build context `directory`")
	asJSON := fs.Bool("json", false, "emit the explanation as JSON")
	if err := fs.Parse(args); err != nil {
		return errUsage
	}
	if fs.NArg() != 1 {
		fmt.Fprintln(stderr, "expected exactly one PATH to explain")
		return errUsage
	}

	exp, err := dctx.Explain(dctx.Options{Context: *dir, Dockerfile: *dockerfile}, fs.Arg(0))
	if err != nil {
		return err
	}

	if *asJSON {
		enc := json.NewEncoder(stdout)
		enc.SetIndent("", "  ")
		return enc.Encode(exp)
	}

	fmt.Fprintf(stdout, "%s: %s\n", exp.Path, exp.Status)
	if !exp.Exists {
		fmt.Fprintln(stdout, "  (path does not exist in the context)")
	}
	if len(exp.Rules) == 0 {
		fmt.Fprintf(stdout, "  no rule in %s matches; included by default\n",
			ignorefileLabel(exp.Ignorefile))
		return nil
	}
	for _, r := range exp.Rules {
		effect := "ignored"
		if r.Negated {
			effect = "re-included"
		}
		line := fmt.Sprintf("  %s:%d", ignorefileLabel(exp.Ignorefile), r.Line)
		fmt.Fprintf(stdout, "%-24s %-24s %s", line, r.Rule, effect)
		if r.Decisive {
			fmt.Fprint(stdout, "  (decisive)")
		}
		fmt.Fprintln(stdout)
	}
	return nil
}

func ignorefileLabel(name string) string {
	if name == "" {
		return "(no ignore file)"
	}
	return name
}

func cmdInstallPlugin(args []string, stdout, stderr io.Writer) error {
	fs := newFlagSet("install-docker-plugin", stderr)
	system := fs.Bool("system", false, "install for all users instead of the current one")
	if err := fs.Parse(args); err != nil {
		return errUsage
	}
	if fs.NArg() != 0 {
		fmt.Fprintln(stderr, "install-docker-plugin takes no arguments")
		return errUsage
	}

	path, err := dctx.InstallPlugin(*system)
	if err != nil {
		return err
	}
	fmt.Fprintf(stdout, "installed %s\nrun it with: docker %s ls\n", path, dctx.PluginName)
	return nil
}
