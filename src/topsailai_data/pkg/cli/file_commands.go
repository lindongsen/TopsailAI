// Package cli implements the file and folder command group.
//
// The "file" command group exposes the same capabilities as the TopsailAI file
// tool so an agent can read, inspect, and edit files through the CLI. Every
// command delegates to the filetool package; this file only parses arguments,
// applies boundary configuration, and formats output.
package cli

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"

	"github.com/topsailai/topsailai_data/pkg/filetool"
	"github.com/topsailai/topsailai_data/pkg/manager"
	"golang.org/x/term"
	"gopkg.in/yaml.v3"
)

// fileOptions builds filetool options from boundary configuration.
//
// The configuration is read once at the CLI boundary and passed down as an
// explicit value, so the library never reads process-wide environment
// variables.
func fileOptions(mgr *manager.Manager) filetool.Options {
	opts := filetool.DefaultOptions()
	if mgr == nil {
		return opts
	}
	cfg := mgr.Config()
	if cfg == nil {
		return opts
	}
	if cfg.FileMaxBytes > 0 {
		opts.TruncateLimit = cfg.FileMaxBytes
	}
	if len(cfg.FileNoTruncateExtensions) > 0 {
		opts.NoTruncateExtensions = cfg.FileNoTruncateExtensions
	}
	return opts
}

// runFile dispatches the "file" command group to its subcommand.
func runFile(ctx context.Context, mgr *manager.Manager, args []string) error {
	if len(args) == 0 {
		printFileUsage(os.Stdout)
		return nil
	}

	name := args[0]
	for _, sub := range fileSubcommands() {
		if sub.Name == name {
			for _, a := range args[1:] {
				if a == "-h" || a == "--help" {
					fmt.Fprintf(os.Stdout, "Usage: topsailai-data file %s\n", sub.Usage)
					return nil
				}
			}
			return sub.Run(ctx, mgr, args[1:])
		}
	}
	return fmt.Errorf("unknown file subcommand %q", name)
}

// fileSubcommands returns the registered "file" subcommands.
func fileSubcommands() []Command {
	return []Command{
		{Name: "read", Usage: "read <file_path> [--seek n] [--size n]", Run: runFileRead},
		{Name: "read-lines", Usage: "read-lines <file_path> [--start n] [--end n]", Run: runFileReadLines},
		{Name: "read-around", Usage: "read-around <file_path> <line_number> [--context n]", Run: runFileReadAround},
		{Name: "read-context", Usage: "read-context <file_path> <pattern> [--context n] [--case-sensitive]", Run: runFileReadContext},
		{Name: "read-files", Usage: "read-files <file_path...> [--format yaml|json]", Run: runFileReadFiles},
		{Name: "write", Usage: "write <file_path> [--content <text>|--from <path|->] [--seek n] [--insert]", Run: runFileWrite},
		{Name: "append", Usage: "append <file_path> [--content <text>|--from <path|->]", Run: runFileAppend},
		{Name: "exists", Usage: "exists <name=path...> [--format yaml|json]", Run: runFileExists},
		{Name: "mkdirs", Usage: "mkdirs <absolute_dir...>", Run: runFileMkdirs},
		{Name: "list-dirs", Usage: "list-dirs <dir...> [--format yaml|json]", Run: runFileListDirs},
		{Name: "size", Usage: "size <file_path>", Run: runFileSize},
		{Name: "overwrite-lines", Usage: "overwrite-lines <file_path> <start_num> [--end n] [--content <text>|--from <path|->]", Run: runFileOverwriteLines},
		{Name: "insert", Usage: "insert <file_path> <line_num> [--content <text>|--from <path|->] [--before]", Run: runFileInsert},
	}
}

// printFileUsage writes the "file" command group usage.
func printFileUsage(w io.Writer) {
	fmt.Fprintln(w, "Usage: topsailai-data file <subcommand> [arguments]")
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Subcommands:")
	for _, sub := range fileSubcommands() {
		fmt.Fprintf(w, "  %-16s %s\n", sub.Name, sub.Usage)
	}
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Notes:")
	fmt.Fprintln(w, "  read truncates content whose extension is not whitelisted; the limit is")
	fmt.Fprintln(w, "  TOPSAILAI_DATA_FILE_MAX_BYTES (default 30000).")
	fmt.Fprintln(w, "  --end 0 reads only --start; --end -1 reads through the end of the file.")
	fmt.Fprintln(w, "  overwrite-lines and insert print a unified diff of the change.")
	fmt.Fprintln(w, "  write, append, overwrite-lines, and insert read redirected stdin when")
	fmt.Fprintln(w, "  neither --content nor --from is given.")
}

// runFileRead implements "file read".
func runFileRead(_ context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("file read")
	seek := fs.Int64("seek", 0, "byte offset to start reading; negative counts from the end")
	size := fs.Int64("size", -1, "maximum bytes to read; -1 reads to the end")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 1, 1); err != nil {
		return fmt.Errorf("file read: %w", err)
	}

	content, err := filetool.ReadFile(remaining[0], filetool.ReadFileOptions{
		Seek:    *seek,
		Size:    *size,
		Options: fileOptions(mgr),
	})
	if err != nil {
		return fmt.Errorf("file read: %w", err)
	}
	fmt.Fprint(os.Stdout, content)
	return nil
}

// runFileReadLines implements "file read-lines".
func runFileReadLines(_ context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("file read-lines")
	start := fs.Int("start", 1, "1-based first line to read")
	end := fs.Int("end", 0, "1-based last line; 0 reads only --start, -1 reads to the end")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 1, 1); err != nil {
		return fmt.Errorf("file read-lines: %w", err)
	}

	content, err := filetool.ReadFileLines(remaining[0], filetool.ReadFileLinesOptions{
		StartNum: *start,
		EndNum:   *end,
	})
	if err != nil {
		return fmt.Errorf("file read-lines: %w", err)
	}
	fmt.Fprint(os.Stdout, content)
	return nil
}

// runFileReadAround implements "file read-around".
func runFileReadAround(_ context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("file read-around")
	contextNum := fs.Int("context", 10, "lines of context before and after the target")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 2, 2); err != nil {
		return fmt.Errorf("file read-around: %w", err)
	}

	lineNumber, err := parseIntArg(remaining[1], "line_number")
	if err != nil {
		return fmt.Errorf("file read-around: %w", err)
	}

	content, err := filetool.ReadFileAroundLine(remaining[0], filetool.ReadFileAroundLineOptions{
		LineNumber: lineNumber,
		ContextNum: *contextNum,
	})
	if err != nil {
		return fmt.Errorf("file read-around: %w", err)
	}
	fmt.Fprint(os.Stdout, content)
	return nil
}

// runFileReadContext implements "file read-context".
func runFileReadContext(_ context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("file read-context")
	contextNum := fs.Int("context", 10, "lines of context before and after each match")
	caseSensitive := fs.Bool("case-sensitive", false, "match case-sensitively")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 2, 2); err != nil {
		return fmt.Errorf("file read-context: %w", err)
	}

	content, err := filetool.ReadFileWithContext(remaining[0], filetool.ReadFileWithContextOptions{
		Pattern:       remaining[1],
		ContextNum:    *contextNum,
		CaseSensitive: *caseSensitive,
	})
	if err != nil {
		return fmt.Errorf("file read-context: %w", err)
	}
	fmt.Fprint(os.Stdout, content)
	return nil
}

// runFileReadFiles implements "file read-files".
func runFileReadFiles(_ context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("file read-files")
	format := fs.String("format", "yaml", "output format: yaml or json")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 1, -1); err != nil {
		return fmt.Errorf("file read-files: %w", err)
	}

	result, err := filetool.ReadFiles(remaining, filetool.ReadFileOptions{Size: -1, Options: fileOptions(mgr)})
	if err != nil {
		return fmt.Errorf("file read-files: %w", err)
	}
	return printStructured(*format, result)
}

// runFileWrite implements "file write".
func runFileWrite(_ context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("file write")
	content := fs.String("content", "", "content to write")
	from := fs.String("from", "", "local file to read content from (use - for stdin; stdin is read when omitted)")
	seek := fs.Int64("seek", 0, "byte offset where writing starts; negative counts from the end")
	insert := fs.Bool("insert", false, "insert content instead of overwriting")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 1, 1); err != nil {
		return fmt.Errorf("file write: %w", err)
	}

	text, err := resolveContent(*content, fs.Changed("content"), *from)
	if err != nil {
		return fmt.Errorf("file write: %w", err)
	}
	if err := filetool.WriteFile(remaining[0], text, filetool.WriteFileOptions{
		Seek:   *seek,
		Insert: *insert,
	}); err != nil {
		return fmt.Errorf("file write: %w", err)
	}
	fmt.Fprintln(os.Stdout, "OK")
	return nil
}

// runFileAppend implements "file append".
func runFileAppend(_ context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("file append")
	content := fs.String("content", "", "content to append")
	from := fs.String("from", "", "local file to read content from (use - for stdin; stdin is read when omitted)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 1, 1); err != nil {
		return fmt.Errorf("file append: %w", err)
	}

	text, err := resolveContent(*content, fs.Changed("content"), *from)
	if err != nil {
		return fmt.Errorf("file append: %w", err)
	}
	if err := filetool.AppendFile(remaining[0], text); err != nil {
		return fmt.Errorf("file append: %w", err)
	}
	fmt.Fprintln(os.Stdout, "OK")
	return nil
}

// runFileExists implements "file exists".
func runFileExists(_ context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("file exists")
	format := fs.String("format", "yaml", "output format: yaml or json")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 1, -1); err != nil {
		return fmt.Errorf("file exists: %w", err)
	}

	checks := make(map[string]string, len(remaining))
	for _, pair := range remaining {
		name, path, ok := strings.Cut(pair, "=")
		if !ok || name == "" || path == "" {
			return fmt.Errorf("file exists: expected name=path, got %q", pair)
		}
		checks[name] = path
	}

	result, err := filetool.CheckFilesExisting(checks)
	if err != nil {
		return fmt.Errorf("file exists: %w", err)
	}
	return printStructured(*format, result)
}

// runFileMkdirs implements "file mkdirs".
func runFileMkdirs(_ context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("file mkdirs")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 1, -1); err != nil {
		return fmt.Errorf("file mkdirs: %w", err)
	}

	if err := filetool.MakeDirs(remaining); err != nil {
		return fmt.Errorf("file mkdirs: %w", err)
	}
	fmt.Fprintln(os.Stdout, "OK")
	return nil
}

// runFileListDirs implements "file list-dirs".
func runFileListDirs(_ context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("file list-dirs")
	format := fs.String("format", "yaml", "output format: yaml or json")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 1, -1); err != nil {
		return fmt.Errorf("file list-dirs: %w", err)
	}

	result, err := filetool.ListDirs(remaining)
	if err != nil {
		return fmt.Errorf("file list-dirs: %w", err)
	}
	return printStructured(*format, result)
}

// runFileSize implements "file size".
func runFileSize(_ context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("file size")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 1, 1); err != nil {
		return fmt.Errorf("file size: %w", err)
	}

	size, err := filetool.FileSize(remaining[0])
	if err != nil {
		return fmt.Errorf("file size: %w", err)
	}
	fmt.Fprintln(os.Stdout, size)
	return nil
}

// runFileOverwriteLines implements "file overwrite-lines".
func runFileOverwriteLines(_ context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("file overwrite-lines")
	end := fs.Int("end", 0, "1-based last line; 0 replaces only start_num, -1 replaces to the end")
	content := fs.String("content", "", "replacement content")
	from := fs.String("from", "", "local file to read content from (use - for stdin; stdin is read when omitted)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 2, 2); err != nil {
		return fmt.Errorf("file overwrite-lines: %w", err)
	}

	startNum, err := parseIntArg(remaining[1], "start_num")
	if err != nil {
		return fmt.Errorf("file overwrite-lines: %w", err)
	}
	text, err := resolveContent(*content, fs.Changed("content"), *from)
	if err != nil {
		return fmt.Errorf("file overwrite-lines: %w", err)
	}

	diff, err := filetool.OverwriteLines(remaining[0], filetool.OverwriteLinesOptions{
		StartNum: startNum,
		EndNum:   *end,
		Content:  text,
	})
	if err != nil {
		return fmt.Errorf("file overwrite-lines: %w", err)
	}
	fmt.Fprint(os.Stdout, diff)
	return nil
}

// runFileInsert implements "file insert".
func runFileInsert(_ context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("file insert")
	content := fs.String("content", "", "content to insert")
	from := fs.String("from", "", "local file to read content from (use - for stdin; stdin is read when omitted)")
	before := fs.Bool("before", false, "insert before the line instead of after")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 2, 2); err != nil {
		return fmt.Errorf("file insert: %w", err)
	}

	lineNum, err := parseIntArg(remaining[1], "line_num")
	if err != nil {
		return fmt.Errorf("file insert: %w", err)
	}
	text, err := resolveContent(*content, fs.Changed("content"), *from)
	if err != nil {
		return fmt.Errorf("file insert: %w", err)
	}

	diff, err := filetool.InsertContent(remaining[0], filetool.InsertContentOptions{
		LineNum: lineNum,
		Before:  *before,
		Content: text,
	})
	if err != nil {
		return fmt.Errorf("file insert: %w", err)
	}
	fmt.Fprint(os.Stdout, diff)
	return nil
}

// resolveContent returns the content for a write command.
//
// Precedence: an explicit --content value wins, then --from <path>, then
// --from -, and finally redirected stdin. Reading stdin when neither flag is
// set matches the convention already used by create and put, so a caller can
// pipe content instead of repeating it on the command line. When stdin is an
// interactive terminal the content stays empty, which is a valid request for
// deleting a line range.
//
// contentSet reports whether --content was passed explicitly, so that
// an explicit empty --content still means "empty content" rather than "read stdin".
func resolveContent(content string, contentSet bool, from string) (string, error) {
	if from == "" {
		if contentSet || stdinIsTerminal() {
			return content, nil
		}
		data, err := io.ReadAll(os.Stdin)
		if err != nil {
			return "", err
		}
		return string(data), nil
	}
	if from == "-" {
		data, err := io.ReadAll(os.Stdin)
		if err != nil {
			return "", err
		}
		return string(data), nil
	}
	data, err := os.ReadFile(from)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

// stdinIsTerminal reports whether stdin is an interactive terminal. When stdin
// is not a terminal the caller has redirected or piped input, so a write
// command may read its content from it.
func stdinIsTerminal() bool {
	if os.Stdin == nil {
		return false
	}
	return term.IsTerminal(int(os.Stdin.Fd()))
}

// parseIntArg parses a required integer argument.
func parseIntArg(value, name string) (int, error) {
	parsed, err := strconv.Atoi(strings.TrimSpace(value))
	if err != nil {
		return 0, fmt.Errorf("invalid %s %q: must be an integer", name, value)
	}
	return parsed, nil
}

// printStructured writes a value as YAML or JSON.
func printStructured(format string, value any) error {
	switch strings.ToLower(strings.TrimSpace(format)) {
	case "", "yaml":
		out, err := yaml.Marshal(value)
		if err != nil {
			return err
		}
		fmt.Fprint(os.Stdout, string(out))
		return nil
	case "json":
		out, err := json.MarshalIndent(value, "", "  ")
		if err != nil {
			return err
		}
		fmt.Fprintln(os.Stdout, string(out))
		return nil
	default:
		return fmt.Errorf("invalid --format %q: must be yaml or json", format)
	}
}
