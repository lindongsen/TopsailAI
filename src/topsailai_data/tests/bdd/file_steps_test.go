package bdd

import (
	"archive/tar"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/cucumber/godog"
)

// scenarioPath resolves an argument that starts with "@" to a path inside the
// scenario workspace. Any other argument is returned unchanged so flags and
// literal values pass through untouched.
//
// The "@" convention keeps feature files free of absolute paths while still
// letting a scenario address files it created itself. It is used for
// operating-system paths such as a --from source; object-relative paths are
// written plainly because they are already relative to the object folder.
func scenarioPath(state *scenarioContext, argument string) (string, error) {
	if !strings.HasPrefix(argument, "@") {
		return argument, nil
	}
	relative := strings.TrimPrefix(argument, "@")
	if relative == "" {
		return "", fmt.Errorf("scenario path marker @ must be followed by a relative path")
	}
	resolved := filepath.Join(state.root, relative)
	base := state.root + string(os.PathSeparator)
	if resolved != state.root && !strings.HasPrefix(resolved, base) {
		return "", fmt.Errorf("scenario path %q escapes the scenario workspace", relative)
	}
	return resolved, nil
}

// unescapeContent expands the escape sequences a feature file can express in a
// single table cell.
func unescapeContent(value string) string {
	replacer := strings.NewReplacer(`\n`, "\n", `\t`, "\t", `\r`, "\r", `\\`, `\`)
	return replacer.Replace(value)
}

// givenScenarioFile writes a file inside the scenario workspace.
//
// Such a file lives on the operating-system file system, so it is only used as
// a --from source. Object content is created with givenObjectWithFiles.
func givenScenarioFile(ctx context.Context, relative, content string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	path, err := scenarioPath(state, "@"+relative)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("create parent folder for %q: %w", relative, err)
	}
	if err := os.WriteFile(path, []byte(unescapeContent(content)), 0o644); err != nil {
		return fmt.Errorf("write scenario file %q: %w", relative, err)
	}
	return nil
}

// givenScenarioRepeatedFile writes a file whose content repeats one character.
//
// It lets a scenario exceed the default read limit without embedding a huge
// literal in the feature file.
func givenScenarioRepeatedFile(ctx context.Context, relative, count, character string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	path, err := scenarioPath(state, "@"+relative)
	if err != nil {
		return err
	}
	repeats, err := strconv.Atoi(strings.TrimSpace(count))
	if err != nil || repeats < 0 {
		return fmt.Errorf("invalid repeat count %q", count)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("create parent folder for %q: %w", relative, err)
	}
	content := strings.Repeat(character, repeats)
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		return fmt.Errorf("write scenario file %q: %w", relative, err)
	}
	return nil
}

// givenScenarioFolder creates a folder inside the scenario workspace.
func givenScenarioFolder(ctx context.Context, relative string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	path, err := scenarioPath(state, "@"+relative)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(path, 0o755); err != nil {
		return fmt.Errorf("create scenario folder %q: %w", relative, err)
	}
	return nil
}

// givenObjectWithFiles creates one data object whose actual data holds the
// files listed in the table.
//
// The table has a "path" and a "content" column. The mandatory marker file is
// added automatically when the table does not provide it, so a scenario only
// lists the files it actually exercises.
func givenObjectWithFiles(ctx context.Context, name string, table *godog.Table) error {
	files := make(map[string]string, len(table.Rows))
	hasMarker := false
	for index, row := range table.Rows {
		if len(row.Cells) != 2 {
			return fmt.Errorf("each object file row must contain a path and a content cell")
		}
		path := strings.TrimSpace(row.Cells[0].Value)
		content := unescapeContent(row.Cells[1].Value)
		if index == 0 && path == "path" && content == "content" {
			continue
		}
		if path == "" {
			return fmt.Errorf("object file path must not be empty")
		}
		if path == name+".md" {
			hasMarker = true
		}
		files[path] = content
	}
	if !hasMarker {
		files[name+".md"] = "marker for " + name
	}

	return createObjectWithFiles(ctx, name, files)
}

// createObjectWithFiles creates one data object from a file map.
//
// The files are packed into a tar archive and handed to the create command, so
// the object is built through the public CLI exactly as a user would build it.
func createObjectWithFiles(ctx context.Context, name string, files map[string]string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	archive := filepath.Join(state.root, "object-"+name+".tar")
	if err := writeTarArchive(archive, files); err != nil {
		return err
	}
	runCLI(ctx, state, []string{
		"create", name,
		"--description", "scenario object " + name,
		"--from", archive,
	}, strings.NewReader(""))
	if state.result.code != 0 {
		return fmt.Errorf("create object %q failed: stderr=%q stdout=%q", name, state.result.stderr, state.result.stdout)
	}
	return nil
}

// writeTarArchive writes a tar archive holding the given files.
//
// The archive is the transport used to create an object with several files in
// one command, so a scenario can build a realistic object folder tree.
func writeTarArchive(archive string, files map[string]string) error {
	if err := os.MkdirAll(filepath.Dir(archive), 0o755); err != nil {
		return fmt.Errorf("create archive folder: %w", err)
	}
	file, err := os.Create(archive)
	if err != nil {
		return fmt.Errorf("create archive %q: %w", archive, err)
	}
	defer file.Close()

	writer := tar.NewWriter(file)
	paths := make([]string, 0, len(files))
	for path := range files {
		paths = append(paths, path)
	}
	sort.Strings(paths)
	for _, path := range paths {
		content := files[path]
		header := &tar.Header{
			Name: path,
			Mode: 0o644,
			Size: int64(len(content)),
		}
		if err := writer.WriteHeader(header); err != nil {
			return fmt.Errorf("write tar header %q: %w", path, err)
		}
		if _, err := writer.Write([]byte(content)); err != nil {
			return fmt.Errorf("write tar body %q: %w", path, err)
		}
	}
	if err := writer.Close(); err != nil {
		return fmt.Errorf("close tar archive %q: %w", archive, err)
	}
	return nil
}

// runFileArguments runs the "file" command group with a table of arguments.
//
// Each row contributes exactly one argument. Arguments starting with "@" are
// resolved inside the scenario workspace so a --from source can be addressed
// without an absolute path; every other argument is passed through unchanged,
// which is how object-relative paths reach the CLI.
func runFileArguments(ctx context.Context, table *godog.Table) error {
	return runFileTable(ctx, table, strings.NewReader(""))
}

// runFileArgumentsWithStdin runs the "file" command group with a table of
// arguments and pipes the given content into stdin. It proves that a write
// command reads redirected stdin when no --content or --from flag is given.
func runFileArgumentsWithStdin(ctx context.Context, content string, table *godog.Table) error {
	return runFileTable(ctx, table, strings.NewReader(unescapeContent(content)))
}

// runFileTable builds the argument list and runs the CLI once.
func runFileTable(ctx context.Context, table *godog.Table, input *strings.Reader) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}

	args := make([]string, 0, len(table.Rows)+1)
	args = append(args, "file")
	for _, row := range table.Rows {
		if len(row.Cells) != 1 {
			return fmt.Errorf("each file argument row must contain one cell")
		}
		resolved, err := scenarioPath(state, row.Cells[0].Value)
		if err != nil {
			return err
		}
		args = append(args, resolved)
	}

	runCLI(ctx, state, args, input)
	return nil
}

// objectFileContent reads one file inside an object through the public CLI.
func objectFileContent(ctx context.Context, name, path string) (string, error) {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return "", err
	}
	runCLI(ctx, state, []string{"get", name, path}, strings.NewReader(""))
	if state.result.code != 0 {
		return "", fmt.Errorf("get %s from %q failed: stderr=%q", path, name, state.result.stderr)
	}
	return string(state.result.stdout), nil
}

// objectFileEquals verifies the exact content of one file inside an object.
func objectFileEquals(ctx context.Context, name, path, content string) error {
	actual, err := objectFileContent(ctx, name, path)
	if err != nil {
		return err
	}
	expected := unescapeContent(content)
	if actual != expected {
		return fmt.Errorf("expected %q in object %q to equal %q, got %q", path, name, expected, actual)
	}
	return nil
}

// objectFileContains verifies that one file inside an object contains a
// fragment.
func objectFileContains(ctx context.Context, name, path, fragment string) error {
	actual, err := objectFileContent(ctx, name, path)
	if err != nil {
		return err
	}
	expected := unescapeContent(fragment)
	if !strings.Contains(actual, expected) {
		return fmt.Errorf("expected %q in object %q to contain %q, got %q", path, name, expected, actual)
	}
	return nil
}

// objectFileDoesNotContain verifies that one file inside an object lacks a
// fragment.
func objectFileDoesNotContain(ctx context.Context, name, path, fragment string) error {
	actual, err := objectFileContent(ctx, name, path)
	if err != nil {
		return err
	}
	expected := unescapeContent(fragment)
	if strings.Contains(actual, expected) {
		return fmt.Errorf("expected %q in object %q not to contain %q, got %q", path, name, expected, actual)
	}
	return nil
}

// objectFileHasSize verifies the byte size of one file inside an object.
func objectFileHasSize(ctx context.Context, name, path, size string) error {
	actual, err := objectFileContent(ctx, name, path)
	if err != nil {
		return err
	}
	expected, err := strconv.ParseInt(strings.TrimSpace(size), 10, 64)
	if err != nil {
		return fmt.Errorf("invalid expected size %q: %w", size, err)
	}
	if int64(len(actual)) != expected {
		return fmt.Errorf("expected %q in object %q to have size %d, got %d", path, name, expected, len(actual))
	}
	return nil
}

// scenarioFileContains verifies that a scenario file contains a fragment.
func scenarioFileContains(ctx context.Context, relative, fragment string) error {
	content, err := readScenarioFile(ctx, relative)
	if err != nil {
		return err
	}
	expected := unescapeContent(fragment)
	if !strings.Contains(content, expected) {
		return fmt.Errorf("expected %q to contain %q, got %q", relative, expected, content)
	}
	return nil
}

// scenarioFileDoesNotContain verifies that a scenario file lacks a fragment.
func scenarioFileDoesNotContain(ctx context.Context, relative, fragment string) error {
	content, err := readScenarioFile(ctx, relative)
	if err != nil {
		return err
	}
	expected := unescapeContent(fragment)
	if strings.Contains(content, expected) {
		return fmt.Errorf("expected %q not to contain %q, got %q", relative, expected, content)
	}
	return nil
}

// scenarioFileEquals verifies the exact content of a scenario file.
func scenarioFileEquals(ctx context.Context, relative, content string) error {
	actual, err := readScenarioFile(ctx, relative)
	if err != nil {
		return err
	}
	expected := unescapeContent(content)
	if actual != expected {
		return fmt.Errorf("expected %q to equal %q, got %q", relative, expected, actual)
	}
	return nil
}

// scenarioFileHasSize verifies the byte size of a scenario file.
func scenarioFileHasSize(ctx context.Context, relative, size string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	path, err := scenarioPath(state, "@"+relative)
	if err != nil {
		return err
	}
	info, err := os.Stat(path)
	if err != nil {
		return fmt.Errorf("stat scenario file %q: %w", relative, err)
	}
	expected, err := strconv.ParseInt(strings.TrimSpace(size), 10, 64)
	if err != nil {
		return fmt.Errorf("invalid expected size %q: %w", size, err)
	}
	if info.Size() != expected {
		return fmt.Errorf("expected %q to have size %d, got %d", relative, expected, info.Size())
	}
	return nil
}

// scenarioFolderExists verifies that a scenario folder exists.
func scenarioFolderExists(ctx context.Context, relative string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	path, err := scenarioPath(state, "@"+relative)
	if err != nil {
		return err
	}
	info, err := os.Stat(path)
	if err != nil {
		return fmt.Errorf("expected scenario folder %q to exist: %w", relative, err)
	}
	if !info.IsDir() {
		return fmt.Errorf("expected %q to be a folder", relative)
	}
	return nil
}

// readScenarioFile reads a scenario file by its workspace-relative name.
func readScenarioFile(ctx context.Context, relative string) (string, error) {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return "", err
	}
	path, err := scenarioPath(state, "@"+relative)
	if err != nil {
		return "", err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("read scenario file %q: %w", relative, err)
	}
	return string(data), nil
}

// givenObjectWithRepeatedFile creates one data object holding a single file
// whose content repeats one character.
//
// It lets a scenario exceed the default read limit without embedding a huge
// literal in the feature file.
func givenObjectWithRepeatedFile(ctx context.Context, name, path, count, character string) error {
	repeats, err := strconv.Atoi(strings.TrimSpace(count))
	if err != nil || repeats < 0 {
		return fmt.Errorf("invalid repeat count %q", count)
	}
	files := map[string]string{
		name + ".md": "marker for " + name,
		path:         strings.Repeat(character, repeats),
	}
	return createObjectWithFiles(ctx, name, files)
}

// objectRootListingContains verifies that the object root listing contains an
// entry name.
//
// The listing is produced by the public CLI so the assertion covers the
// list-dirs command rather than the library alone.
func objectRootListingContains(ctx context.Context, name, fragment string) error {
	return checkObjectRootListing(ctx, name, fragment, true)
}

// objectRootListingDoesNotContain verifies that the object root listing lacks an
// entry name.
func objectRootListingDoesNotContain(ctx context.Context, name, fragment string) error {
	return checkObjectRootListing(ctx, name, fragment, false)
}

// checkObjectRootListing runs list-dirs on the object root and compares the
// output against a fragment.
func checkObjectRootListing(ctx context.Context, name, fragment string, want bool) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	runCLI(ctx, state, []string{"file", "list-dirs", ".", "--object", name, "--format", "json"}, strings.NewReader(""))
	if state.result.code != 0 {
		return fmt.Errorf("list-dirs on object %q failed: stderr=%q", name, state.result.stderr)
	}
	got := strings.Contains(string(state.result.stdout), fragment)
	if got != want {
		return fmt.Errorf("expected object %q root listing contains %q to be %t, got %t (stdout=%q)", name, fragment, want, got, state.result.stdout)
	}
	return nil
}

// existenceResultReports verifies one boolean in the exists command output.
//
// The output is decoded structurally so a scenario asserts the reported value
// instead of merely the presence of a name.
func existenceResultReports(ctx context.Context, name, expected string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	var result map[string]bool
	if err := json.Unmarshal(state.result.stdout, &result); err != nil {
		return fmt.Errorf("decode exists output %q: %w", state.result.stdout, err)
	}
	value, ok := result[name]
	if !ok {
		return fmt.Errorf("exists output %q has no entry %q", state.result.stdout, name)
	}
	want := expected == "true"
	if value != want {
		return fmt.Errorf("expected exists entry %q to be %t, got %t", name, want, value)
	}
	return nil
}
