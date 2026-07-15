// Package cli implements the individual subcommands for topsailai_data.
package cli

import (
	"archive/tar"
	"context"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"github.com/topsailai/topsailai_data/pkg/manager"
	"github.com/topsailai/topsailai_data/pkg/models"
)
// runCreate implements the "create" command.
func runCreate(ctx context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("create")
	classify := fs.String("classify", "", "comma-separated classify directories after the time prefix")
	tags := fs.String("tag", "", "comma-separated tags for the object")
	from := fs.String("from", "", "local file or tar archive to use as initial actual data (use - for stdin)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	remaining := fs.Args()
	if err := requireArgs(remaining, 1, 1); err != nil {
		return fmt.Errorf("create: %w", err)
	}

	name := remaining[0]
	opts := manager.CreateObjectOptions{
		Classify: splitList(*classify),
		Tags:     splitList(*tags),
	}

	if *from != "" {
		r, err := openInput(*from)
		if err != nil {
			return fmt.Errorf("create: open input: %w", err)
		}
		defer r.Close()

		if *from == "-" {
			// stdin: require explicit archive format; treat as tar for now.
			opts.Data = r
		} else if isTarArchive(*from) {
			opts.Data = r
		} else {
			// Plain file: wrap as a single-file archive so the manager can
			// write it as actual data containing one file named <name>.md.
			buf, err := io.ReadAll(r)
			if err != nil {
				return fmt.Errorf("create: read file: %w", err)
			}
			opts.Data = tarBytes(name+".md", buf)
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
	obj, err := mgr.GetObject(ctx, id, false)
	if err != nil {
		return fmt.Errorf("show: %w", err)
	}
	printObject(obj)
	return nil
}

// runList implements the "list" command.
func runList(ctx context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("list")
	tag := fs.String("tag", "", "comma-separated tags to filter by")
	includeDeleted := fs.Bool("include-deleted", false, "include deleted and ceased objects")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if err := requireArgs(fs.Args(), 0, 0); err != nil {
		return fmt.Errorf("list: %w", err)
	}

	opts := models.ListOptions{
		Tags:           splitList(*tag),
		IncludeDeleted: *includeDeleted,
	}
	objects, err := mgr.ListObjects(ctx, opts)
	if err != nil {
		return fmt.Errorf("list: %w", err)
	}
	printObjectList(objects)
	return nil
}

// runSearch implements the "search" command.
func runSearch(ctx context.Context, mgr *manager.Manager, args []string) error {
	fs := newFlagSet("search")
	includeDeleted := fs.Bool("include-deleted", false, "include deleted and ceased objects")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if err := requireArgs(fs.Args(), 1, 1); err != nil {
		return fmt.Errorf("search: %w", err)
	}
	query := fs.Args()[0]

	objects, err := mgr.SearchObjects(ctx, query, models.ListOptions{IncludeDeleted: *includeDeleted})
	if err != nil {
		return fmt.Errorf("search: %w", err)
	}
	printObjectList(objects)
	return nil
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
	from := fs.String("from", "", "local file to read (use - for stdin); default is stdin")
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

// printObject prints a single object's metadata in a human-readable form.
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

// printObjectList prints a compact list of objects.
func printObjectList(objects []*models.Object) {
	if len(objects) == 0 {
		fmt.Println("no objects")
		return
	}
	for _, obj := range objects {
		fmt.Printf("%s  %-10s  %s  [%s]\n", obj.ID, obj.Status, obj.Path, strings.Join(obj.Tags, ", "))
	}
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
