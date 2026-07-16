// Package cli implements the individual subcommands for topsailai_data.
package cli

import (
	"archive/tar"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"golang.org/x/term"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/manager"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// runCreate implements the "create" command.
func runCreate(ctx context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("create")
	classify := fs.String("classify", "", "comma-separated classify directories after the time prefix")
	tags := fs.String("tag", "", "comma-separated tags for the object")
	from := fs.String("from", "", "local file or tar archive to use as initial actual data (use - for stdin); default is stdin when stdin is redirected")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 1, 1); err != nil {
		return fmt.Errorf("create: %w", err)
	}

	name := remaining[0]
	opts := manager.CreateObjectOptions{
		Classify: flattenClassifyArgs(splitList(*classify)),
		Tags:     splitList(*tags),
	}

	var r io.ReadCloser
	src := *from
	if src != "" {
		var err error
		r, err = openInput(src)
		if err != nil {
			return fmt.Errorf("create: open input: %w", err)
		}
		defer r.Close()
	} else if !term.IsTerminal(int(os.Stdin.Fd())) {
		// No --from and stdin is redirected: read object.md content from stdin.
		r = io.NopCloser(os.Stdin)
	}

	if r != nil {
		buf, err := io.ReadAll(r)
		if err != nil {
			return fmt.Errorf("create: read input: %w", err)
		}
		if len(buf) > 0 {
			if isTarBytes(buf) {
				opts.Data = bytes.NewReader(buf)
			} else {
				opts.Data = tarBytes(name+".md", buf)
			}
		}
	}

	obj, err := mgr.CreateObject(ctx, name, opts)
	if err != nil {
		return fmt.Errorf("create: %w", err)
	}
	fmt.Printf("created object %s at %s\n", obj.ID, obj.Path)
	return nil
}

// tarBytes returns a reader that yields a tar archive containing a single
// regular file with the given name and content.
func tarBytes(filename string, content []byte) io.Reader {
	pr, pw := io.Pipe()
	go func() {
		tw := tar.NewWriter(pw)
		hdr := &tar.Header{
			Name: filename,
			Mode: 0o644,
			Size: int64(len(content)),
		}
		if err := tw.WriteHeader(hdr); err != nil {
			_ = pw.CloseWithError(err)
			return
		}
		if _, err := tw.Write(content); err != nil {
			_ = pw.CloseWithError(err)
			return
		}
		if err := tw.Close(); err != nil {
			_ = pw.CloseWithError(err)
			return
		}
		_ = pw.Close()
	}()
	return pr
}

// runShow implements the "show" command.
func runShow(ctx context.Context, mgr *manager.Manager, args []string) error {
	if err := requireArgs(args, 1, 1); err != nil {
		return fmt.Errorf("show: %w", err)
	}
	id := models.ObjectID(args[0])
	obj, err := mgr.GetObject(ctx, id, true)
	if err != nil {
		return fmt.Errorf("show: %w", err)
	}
	printObject(obj)

	if obj.Status != models.ObjectStatusActive {
		fmt.Println()
		fmt.Printf("--- Actual data unavailable for %s object ---\n", obj.Status)
		return nil
	}

	fmt.Println()
	fmt.Println("--- Markdown ---")
	if err := printObjectMarkdown(ctx, mgr, id); err != nil {
		fmt.Fprintf(os.Stderr, "show: read object.md: %v\n", err)
	}

	fmt.Println()
	fmt.Println("--- folder structure ---")
	if err := printObjectTree(obj.Name, obj.DataRef); err != nil {
		fmt.Fprintf(os.Stderr, "show: read folder structure: %v\n", err)
	}
	return nil
}

// printObjectMarkdown reads and prints the object\'s mandatory <id>.md file.
func printObjectMarkdown(ctx context.Context, mgr *manager.Manager, id models.ObjectID) error {
	rc, err := mgr.ReadActualFile(ctx, id, string(id)+".md")
	if err != nil {
		return err
	}
	defer rc.Close()
	content, err := io.ReadAll(rc)
	if err != nil {
		return err
	}
	if len(content) == 0 {
		fmt.Println("(empty)")
		return nil
	}
	fmt.Print(string(content))
	if !bytes.HasSuffix(content, []byte("\\n")) {
		fmt.Println()
	}
	return nil
}

// printObjectTree prints a tree-style listing of the object directory,
// excluding the mandatory object marker file and other metadata markers.
func printObjectTree(objectName, dir string) error {
	markerName := objectName + ".md"
	entries, err := os.ReadDir(dir)
	if err != nil {
		return err
	}

	// Filter out the mandatory object marker and metadata marker files.
	var visible []os.DirEntry
	for _, entry := range entries {
		name := entry.Name()
		if name == markerName || isMetadataMarkerName(name) {
			continue
		}
		visible = append(visible, entry)
	}

	if len(visible) == 0 {
		fmt.Println("no additional files")
		return nil
	}

	fmt.Println(objectName + "/")
	return printObjectTreeEntries(dir, visible, "")
}

// printObjectTreeEntries recursively prints directory entries with tree connectors.
func printObjectTreeEntries(dir string, entries []os.DirEntry, prefix string) error {
	for i, entry := range entries {
		isLast := i == len(entries)-1
		connector := "├── "
		if isLast {
			connector = "└── "
		}
		fmt.Printf("%s%s%s\n", prefix, connector, entry.Name())
		if entry.IsDir() {
			nextPrefix := prefix
			if isLast {
				nextPrefix += "    "
			} else {
				nextPrefix += "│   "
			}
			subEntries, err := os.ReadDir(filepath.Join(dir, entry.Name()))
			if err != nil {
				return err
			}
			if err := printObjectTreeEntries(filepath.Join(dir, entry.Name()), subEntries, nextPrefix); err != nil {
				return err
			}
		}
	}
	return nil
}

// isMetadataMarkerName reports whether name is a reserved metadata marker.
func isMetadataMarkerName(name string) bool {
	if name == "metadata.json" {
		return true
	}
	for _, suffix := range []string{".tags", ".lock", ".deleted", ".ceased"} {
		if strings.HasSuffix(name, suffix) {
			return true
		}
	}
	return false
}

// runList implements the "list" command.
func runList(ctx context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("list")
	tag := fs.String("tag", "", "comma-separated tags to filter by")
	includeDeleted := fs.Bool("include-deleted", false, "include deleted and ceased objects")
	offset := fs.Int("offset", 0, "number of results to skip")
	limit := fs.Int("limit", 0, "maximum number of results to return")
	format := fs.String("format", "table", "output format: table or json")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if err := requireArgs(fs.Args(), 0, 0); err != nil {
		return fmt.Errorf("list: %w", err)
	}
	if err := validateListFormat(*format); err != nil {
		return fmt.Errorf("list: %w", err)
	}

	opts := models.ListOptions{
		Tags:           splitList(*tag),
		IncludeDeleted: *includeDeleted,
		Offset:         *offset,
		Limit:          *limit,
	}
	objects, err := mgr.ListObjects(ctx, opts)
	if err != nil {
		return fmt.Errorf("list: %w", err)
	}
	printObjectList(objects, *format)
	return nil
}

// runSearch implements the "search" command.
func runSearch(ctx context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("search")
	includeDeleted := fs.Bool("include-deleted", false, "include deleted and ceased objects")
	offset := fs.Int("offset", 0, "number of results to skip")
	limit := fs.Int("limit", 0, "maximum number of results to return")
	format := fs.String("format", "table", "output format: table or json")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if err := requireArgs(fs.Args(), 1, 1); err != nil {
		return fmt.Errorf("search: %w", err)
	}
	if err := validateListFormat(*format); err != nil {
		return fmt.Errorf("search: %w", err)
	}

	terms, err := parseSearchQuery(fs.Args()[0])
	if err != nil {
		return fmt.Errorf("search: %w", err)
	}

	objects, err := mgr.SearchObjects(ctx, terms, models.ListOptions{
		IncludeDeleted: *includeDeleted,
		Offset:         *offset,
		Limit:          *limit,
	})
	if err != nil {
		return fmt.Errorf("search: %w", err)
	}
	printObjectList(objects, *format)
	return nil
}

// parseSearchQuery splits a raw search query into terms using '|' as the OR
// separator. It rejects whitespace and backslash escapes because the search
// command does not support quoting or escaping.
func parseSearchQuery(query string) ([]string, error) {
	terms, err := manager.ParseSearchQuery(query)
	if err != nil {
		// Translate sentinel into plain messages to preserve existing CLI error text.
		if errors.Is(err, apperrors.ErrInvalidSearchQuery) {
			if strings.ContainsRune(query, '\\') {
				return nil, fmt.Errorf("search query cannot contain backslash escapes")
			}
			if strings.ContainsRune(query, ' ') || strings.ContainsRune(query, '\t') {
				return nil, fmt.Errorf("search query cannot contain spaces or tabs")
			}
			return nil, fmt.Errorf("search query contains an empty term")
		}
		return nil, err
	}
	return terms, nil
}

// runTag implements the "tag" command.
func runTag(ctx context.Context, mgr *manager.Manager, args []string) error {
	if err := requireArgs(args, 3, 3); err != nil {
		return fmt.Errorf("tag: %w", err)
	}
	sub := args[0]
	id := models.ObjectID(args[1])
	tag := args[2]

	switch sub {
	case "add":
		if err := mgr.AddTag(ctx, id, tag); err != nil {
			return fmt.Errorf("tag add: %w", err)
		}
		fmt.Printf("added tag %q to %s\n", tag, id)
	case "remove":
		if err := mgr.RemoveTag(ctx, id, tag); err != nil {
			return fmt.Errorf("tag remove: %w", err)
		}
		fmt.Printf("removed tag %q from %s\n", tag, id)
	default:
		return fmt.Errorf("tag: unknown subcommand %q (expected add or remove)", sub)
	}
	return nil
}

// runMove implements the "move" command.
func runMove(ctx context.Context, mgr *manager.Manager, args []string) error {
	if err := requireArgs(args, 2, -1); err != nil {
		return fmt.Errorf("move: %w", err)
	}
	id := models.ObjectID(args[0])
	classify := flattenClassifyArgs(args[1:])
	if err := mgr.MoveObject(ctx, id, classify); err != nil {
		return fmt.Errorf("move: %w", err)
	}
	fmt.Printf("moved object %s\n", id)
	return nil
}

// flattenClassifyArgs expands any slash-separated classify segments into a
// flat list. This allows users to write either "move id a/b" or "move id a b".
func flattenClassifyArgs(args []string) []string {
	out := make([]string, 0, len(args))
	for _, arg := range args {
		for _, seg := range strings.Split(arg, "/") {
			seg = strings.TrimSpace(seg)
			if seg != "" {
				out = append(out, seg)
			}
		}
	}
	return out
}

// runDelete implements the "delete" command.
func runDelete(ctx context.Context, mgr *manager.Manager, args []string) error {
	if err := requireArgs(args, 1, 1); err != nil {
		return fmt.Errorf("delete: %w", err)
	}
	id := models.ObjectID(args[0])
	if err := mgr.DeleteObject(ctx, id); err != nil {
		return fmt.Errorf("delete: %w", err)
	}
	fmt.Printf("deleted object %s\n", id)
	return nil
}

// runRecover implements the "recover" command.
func runRecover(ctx context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("recover")
	resume := fs.Bool("resume", false, "resume creation by writing actual data")
	from := fs.String("from", "", "tar archive to write when resuming (use - for stdin)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if err := requireArgs(fs.Args(), 1, 1); err != nil {
		return fmt.Errorf("recover: %w", err)
	}
	id := models.ObjectID(fs.Args()[0])

	var r io.Reader
	if *from != "" {
		in, err := openInput(*from)
		if err != nil {
			return fmt.Errorf("recover: open archive: %w", err)
		}
		defer in.Close()
		r = in
	}

	if err := mgr.RecoverObject(ctx, id, *resume, r); err != nil {
		return fmt.Errorf("recover: %w", err)
	}
	fmt.Printf("recovered object %s\n", id)
	return nil
}

// runGC implements the "gc" command.
func runGC(ctx context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("gc")
	dryRun := fs.Bool("dry-run", false, "list candidates without deleting")
	status := fs.String("status", "", "filter by status: creating, deleted, or ceased")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if err := requireArgs(fs.Args(), 0, 0); err != nil {
		return fmt.Errorf("gc: %w", err)
	}

	filter := strings.ToLower(strings.TrimSpace(*status))
	switch filter {
	case "", "creating", "deleted", "ceased":
	default:
		return fmt.Errorf("gc: invalid status %q", *status)
	}

	// Default GC scans both creating and ceased objects.
	if filter == "" || filter == "ceased" {
		if *dryRun {
			fmt.Println("dry-run: would run GC for ceased objects")
		} else {
			if err := mgr.GC(ctx); err != nil {
				return fmt.Errorf("gc: %w", err)
			}
			fmt.Println("gc completed for ceased objects")
		}
	}

	if filter == "" || filter == "creating" {
		objects, err := mgr.ListCreatingObjects(ctx)
		if err != nil {
			return fmt.Errorf("gc: list creating: %w", err)
		}
		if len(objects) == 0 && filter == "creating" {
			fmt.Println("no creating objects to gc")
			return nil
		}
		for _, obj := range objects {
			if *dryRun {
				fmt.Printf("dry-run: would recover creating object %s at %s\n", obj.ID, obj.Path)
				continue
			}
			if err := mgr.RecoverObject(ctx, obj.ID, false, nil); err != nil {
				return fmt.Errorf("gc: recover creating %s: %w", obj.ID, err)
			}
			fmt.Printf("recovered creating object %s\n", obj.ID)
		}
	}

	if filter == "" || filter == "deleted" {
		objects, err := mgr.ListDeletedObjects(ctx)
		if err != nil {
			return fmt.Errorf("gc: list deleted: %w", err)
		}
		if len(objects) == 0 && filter == "deleted" {
			fmt.Println("no deleted objects to gc")
			return nil
		}
		for _, obj := range objects {
			if *dryRun {
				fmt.Printf("dry-run: would finalize deleted object %s\n", obj.ID)
				continue
			}
			if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
				fmt.Fprintf(os.Stderr, "gc: finalize %s: %v\n", obj.ID, err)
				continue
			}
			fmt.Printf("finalized deleted object %s\n", obj.ID)
		}
	}

	return nil
}

// runGet implements the "get" command.
func runGet(ctx context.Context, mgr *manager.Manager, args []string) error {
	if err := requireArgs(args, 2, 2); err != nil {
		return fmt.Errorf("get: %w", err)
	}
	id := models.ObjectID(args[0])
	filename := args[1]

	rc, err := mgr.ReadActualFile(ctx, id, filename)
	if err != nil {
		return fmt.Errorf("get: %w", err)
	}
	defer rc.Close()

	if _, err := io.Copy(os.Stdout, rc); err != nil {
		return fmt.Errorf("get: copy to stdout: %w", err)
	}
	return nil
}

// runGetArchive implements the "get-archive" command.
func runGetArchive(ctx context.Context, mgr *manager.Manager, args []string) error {
	if err := requireArgs(args, 1, 1); err != nil {
		return fmt.Errorf("get-archive: %w", err)
	}
	id := models.ObjectID(args[0])

	rc, err := mgr.ReadActualArchive(ctx, id)
	if err != nil {
		return fmt.Errorf("get-archive: %w", err)
	}
	defer rc.Close()

	if _, err := io.Copy(os.Stdout, rc); err != nil {
		return fmt.Errorf("get-archive: copy to stdout: %w", err)
	}
	return nil
}

// runPut implements the "put" command.
func runPut(ctx context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("put")
	from := fs.String("from", "", "local file to read (use - for stdin); default is stdin when stdin is redirected")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if err := requireArgs(fs.Args(), 2, 2); err != nil {
		return fmt.Errorf("put: %w", err)
	}
	id := models.ObjectID(fs.Args()[0])
	filename := fs.Args()[1]

	src := *from
	if src == "" {
		if term.IsTerminal(int(os.Stdin.Fd())) {
			return fmt.Errorf("put: --from is required when stdin is a terminal")
		}
		src = "-"
	}
	r, err := openInput(src)
	if err != nil {
		return fmt.Errorf("put: open input: %w", err)
	}
	defer r.Close()

	if err := mgr.WriteActualFile(ctx, id, filename, r); err != nil {
		return fmt.Errorf("put: %w", err)
	}
	fmt.Printf("wrote %s to object %s\n", filename, id)
	return nil
}

// openInput opens an input source. A path of "-" means stdin; the returned
// ReadCloser will not close stdin when closed.
func openInput(path string) (io.ReadCloser, error) {
	if path == "-" {
		return io.NopCloser(os.Stdin), nil
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	return f, nil
}

// runPutArchive implements the "put-archive" command.
func runPutArchive(ctx context.Context, mgr *manager.Manager, args []string) error {
	if err := requireArgs(args, 2, 2); err != nil {
		return fmt.Errorf("put-archive: %w", err)
	}
	id := models.ObjectID(args[0])
	archivePath := args[1]

	r, err := openInput(archivePath)
	if err != nil {
		return fmt.Errorf("put-archive: open archive: %w", err)
	}
	defer r.Close()

	if err := mgr.UpdateActualData(ctx, id, r); err != nil {
		return fmt.Errorf("put-archive: %w", err)
	}
	fmt.Printf("wrote archive to object %s\n", id)
	return nil
}

// printObject prints a single object\'s metadata in a human-readable form.
func printObject(obj *models.Object) {
	fmt.Printf("ID:            %s\n", obj.ID)
	fmt.Printf("Name:          %s\n", obj.Name)
	fmt.Printf("Path:          %s\n", obj.Path)
	fmt.Printf("Status:        %s\n", obj.Status)
	fmt.Printf("SchemaVersion: %d\n", obj.SchemaVersion)
	fmt.Printf("CreatedAt:     %s\n", obj.CreatedAt.Format(time.RFC3339))
	fmt.Printf("UpdatedAt:     %s\n", obj.UpdatedAt.Format(time.RFC3339))
	if obj.DeletedAt != nil {
		fmt.Printf("DeletedAt:     %s\n", obj.DeletedAt.Format(time.RFC3339))
	}
	if obj.CeasedAt != nil {
		fmt.Printf("CeasedAt:      %s\n", obj.CeasedAt.Format(time.RFC3339))
	}
	fmt.Printf("Tags:          %s\n", strings.Join(obj.Tags, ", "))
	fmt.Printf("DataRef:       %s\n", obj.DataRef)
}

// validateListFormat returns an error if format is not a supported list output format.
func validateListFormat(format string) error {
	switch format {
	case "table", "json":
		return nil
	default:
		return fmt.Errorf("unsupported format %q (expected table or json)", format)
	}
}

// printObjectList prints objects using the requested format.
func printObjectList(objects []*models.Object, format string) {
	switch format {
	case "json":
		printObjectListJSON(objects)
	default:
		printObjectListTable(objects)
	}
}

// listObjectJSON is the JSON representation of an object used by list/search output.
type listObjectJSON struct {
	ID            string    `json:"id"`
	Name          string    `json:"name"`
	Path          string    `json:"path"`
	Status        string    `json:"status"`
	Tags          []string  `json:"tags"`
	CreatedAt     time.Time `json:"created_at"`
	UpdatedAt     time.Time `json:"updated_at"`
	SchemaVersion int       `json:"schema_version"`
	DataRef       string    `json:"data_ref"`
}

// printObjectListJSON prints objects as a pretty-printed JSON array.
func printObjectListJSON(objects []*models.Object) {
	items := make([]listObjectJSON, 0, len(objects))
	for _, obj := range objects {
		items = append(items, listObjectJSON{
			ID:            string(obj.ID),
			Name:          obj.Name,
			Path:          obj.Path,
			Status:        string(obj.Status),
			Tags:          obj.Tags,
			CreatedAt:     obj.CreatedAt,
			UpdatedAt:     obj.UpdatedAt,
			SchemaVersion: obj.SchemaVersion,
			DataRef:       obj.DataRef,
		})
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	_ = enc.Encode(items)
}

// printObjectListTable prints objects as a pipe-separated table without truncation.
func printObjectListTable(objects []*models.Object) {
	if len(objects) == 0 {
		fmt.Println("No objects found")
		return
	}

	headers := []string{"ID", "NAME", "STATUS", "PATH", "TAGS", "CREATED AT", "UPDATED AT"}
	rows := make([][]string, 0, len(objects))
	for _, obj := range objects {
		rows = append(rows, []string{
			string(obj.ID),
			obj.Name,
			string(obj.Status),
			obj.Path,
			strings.Join(obj.Tags, ","),
			obj.CreatedAt.Format(time.RFC3339),
			obj.UpdatedAt.Format(time.RFC3339),
		})
	}

	widths := make([]int, len(headers))
	for i, h := range headers {
		widths[i] = len(h)
	}
	for _, row := range rows {
		for i, cell := range row {
			if len(cell) > widths[i] {
				widths[i] = len(cell)
			}
		}
	}

	printRow := func(cells []string) {
		parts := make([]string, len(cells))
		for i, cell := range cells {
			parts[i] = fmt.Sprintf(" %-*s ", widths[i], cell)
		}
		fmt.Println("|" + strings.Join(parts, "|") + "|")
	}

	printRow(headers)
	for _, row := range rows {
		printRow(row)
	}
}

// isTarBytes reports whether buf looks like a tar archive by inspecting its
// first bytes.
func isTarBytes(buf []byte) bool {
	tr := tar.NewReader(bytes.NewReader(buf))
	_, err := tr.Next()
	return err == nil
}

// isTarArchive reports whether a file looks like a tar archive by inspecting
// its first bytes.
func isTarArchive(path string) bool {
	f, err := os.Open(path)
	if err != nil {
		return false
	}
	defer f.Close()
	tr := tar.NewReader(f)
	_, err = tr.Next()
	return err == nil
}
