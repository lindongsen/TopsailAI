package bdd

import (
	"archive/tar"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/cucumber/godog"
	"gopkg.in/yaml.v3"
)

// waitForNewTimePrefixMinute waits until the next object will receive a
// different public time-prefix key than the named existing object.
func waitForNewTimePrefixMinute(ctx context.Context, name string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	priorKey, err := objectTimePrefixKey(ctx, state, name)
	if err != nil {
		return err
	}
	deadline := time.Now().Add(70 * time.Second)
	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		if time.Now().Format("2006/0102/1504") != priorKey {
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	return fmt.Errorf("timed out waiting for a time-prefix minute after %q", name)
}

// objectTimePrefixKey reads an object's public path through the CLI.
func objectTimePrefixKey(ctx context.Context, state *scenarioContext, name string) (string, error) {
	runCLI(ctx, state, []string{"list", "--format", "json"}, strings.NewReader(""))
	if state.result.code != 0 {
		return "", fmt.Errorf("list failed while reading %q: %s", name, state.result.stderr)
	}
	var objects []map[string]any
	if err := json.Unmarshal(state.result.stdout, &objects); err != nil {
		return "", fmt.Errorf("decode list JSON while reading %q: %w", name, err)
	}
	for _, object := range objects {
		if object["id"] != name {
			continue
		}
		path, ok := object["path"].(string)
		if !ok {
			return "", fmt.Errorf("object %q has no public path", name)
		}
		parts := strings.Split(path, "/")
		if len(parts) < 4 {
			return "", fmt.Errorf("object %q has invalid public path %q", name, path)
		}
		return strings.Join(parts[:3], "/"), nil
	}
	return "", fmt.Errorf("object %q not found in public list", name)
}

// sortFixturesHaveDistinctTimePrefixes verifies all sort fixture paths through the CLI.
func sortFixturesHaveDistinctTimePrefixes(ctx context.Context) error {
	objects, err := listObjects(ctx)
	if err != nil {
		return err
	}
	seen := make(map[string]string, 3)
	for _, id := range []string{"list-one", "list-two", "list-three"} {
		var path string
		for _, object := range objects {
			if object["id"] == id {
				path, _ = object["path"].(string)
				break
			}
		}
		parts := strings.Split(path, "/")
		if len(parts) < 4 {
			return fmt.Errorf("sort fixture %q has invalid public path %q", id, path)
		}
		key := strings.Join(parts[:3], "/")
		if previous, exists := seen[key]; exists {
			return fmt.Errorf("sort fixtures %q and %q share time-prefix key %q", previous, id, key)
		}
		seen[key] = id
	}
	return nil
}

// createFromFixture creates an object from a repository fixture.
func createFromFixture(ctx context.Context, name, fixture string) error {
	return createConfiguredFromFixture(ctx, name, fixture, "", "", "")
}

// createConfiguredFromFixture creates an object with optional public flags.
func createConfiguredFromFixture(ctx context.Context, name, fixture, description, tags, classify string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	args := []string{"create", name, "--from", fixturePath(state, fixture)}
	if description != "" {
		args = append(args, "--description", description)
	}
	if tags != "" {
		args = append(args, "--tag", tags)
	}
	if classify != "" {
		args = append(args, "--classify", classify)
	}
	runCLI(ctx, state, args, strings.NewReader(""))
	return nil
}

// createFromStdin creates an object using explicitly supplied stdin content.
func createFromStdin(ctx context.Context, name, description, content string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	runCLI(ctx, state, []string{"create", name, "--description", description}, strings.NewReader(content))
	return nil
}

// runArguments executes the exact argument table, resolving repository fixture paths.
func runArguments(ctx context.Context, table *godog.Table) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	args := make([]string, 0, len(table.Rows))
	for _, row := range table.Rows {
		if len(row.Cells) != 1 {
			return fmt.Errorf("each argument row must contain one cell")
		}
		args = append(args, row.Cells[0].Value)
	}
	for i := range args {
		if i > 0 && args[i-1] == "--from" && args[i] != "-" && !filepath.IsAbs(args[i]) {
			args[i] = filepath.Join(projectRoot, args[i])
		}
	}
	runCLI(ctx, state, args, strings.NewReader(""))
	return nil
}

// commandSucceeds verifies a zero exit status.
func commandSucceeds(ctx context.Context) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	if state.result.code != 0 {
		return fmt.Errorf("command failed with code %d: stderr=%q stdout=%q", state.result.code, state.result.stderr, state.result.stdout)
	}
	return nil
}

// commandFails verifies a non-zero exit status.
func commandFails(ctx context.Context) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	if state.result.code == 0 {
		return fmt.Errorf("command unexpectedly succeeded: stdout=%q", state.result.stdout)
	}
	return nil
}

// commandFailsWith verifies failure and an error fragment.
func commandFailsWith(ctx context.Context, fragment string) error {
	if err := commandFails(ctx); err != nil {
		return err
	}
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	if !strings.Contains(string(state.result.stderr), fragment) && !strings.Contains(string(state.result.stdout), fragment) {
		return fmt.Errorf("expected %q in stderr=%q or stdout=%q", fragment, state.result.stderr, state.result.stdout)
	}
	return nil
}

// stdoutContains verifies a human-readable output fragment.
func stdoutContains(ctx context.Context, fragment string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	if !strings.Contains(string(state.result.stdout), fragment) {
		return fmt.Errorf("expected stdout to contain %q, got %q", fragment, state.result.stdout)
	}
	return nil
}

// stdoutDoesNotContain verifies that a metadata marker is hidden.
func stdoutDoesNotContain(ctx context.Context, fragment string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	if strings.Contains(string(state.result.stdout), fragment) {
		return fmt.Errorf("expected stdout not to contain %q, got %q", fragment, state.result.stdout)
	}
	return nil
}

// listObjects decodes the CLI JSON list structurally.
func listObjects(ctx context.Context) ([]map[string]any, error) {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return nil, err
	}
	runCLI(ctx, state, []string{"list", "--format", "json"}, strings.NewReader(""))
	if state.result.code != 0 {
		return nil, fmt.Errorf("list failed: %s", state.result.stderr)
	}
	var objects []map[string]any
	if err := json.Unmarshal(state.result.stdout, &objects); err != nil {
		return nil, fmt.Errorf("decode list JSON: %w", err)
	}
	return objects, nil
}

// yamlListObjects decodes the default CLI YAML list structurally.
func yamlListObjects(ctx context.Context) ([]map[string]any, error) {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return nil, err
	}
	runCLI(ctx, state, []string{"list", "--format", "yaml"}, strings.NewReader(""))
	if state.result.code != 0 {
		return nil, fmt.Errorf("list failed: %s", state.result.stderr)
	}
	var objects []map[string]any
	if err := yaml.Unmarshal(state.result.stdout, &objects); err != nil {
		return nil, fmt.Errorf("decode list YAML: %w", err)
	}
	return objects, nil
}

// yamlObjectMatches verifies selected metadata fields in decoded YAML output.
func yamlObjectMatches(ctx context.Context, name, description, status string) error {
	objects, err := yamlListObjects(ctx)
	if err != nil {
		return err
	}
	for _, object := range objects {
		if object["id"] == name {
			if object["description"] != description || object["status"] != status {
				return fmt.Errorf("YAML object %q has description=%v status=%v", name, object["description"], object["status"])
			}
			return nil
		}
	}
	return fmt.Errorf("object %q not found in structured YAML list", name)
}

// jsonObjectMatches verifies selected metadata fields in a decoded object.
func jsonObjectMatches(ctx context.Context, name, description, status string) error {
	objects, err := listObjects(ctx)
	if err != nil {
		return err
	}
	for _, object := range objects {
		if object["id"] == name {
			if object["description"] != description || object["status"] != status {
				return fmt.Errorf("object %q has description=%v status=%v", name, object["description"], object["status"])
			}
			return nil
		}
	}
	return fmt.Errorf("object %q not found in structured JSON list", name)
}

// jsonObjectTagsMatches verifies the ordered tag list structurally.
func jsonObjectTagsMatches(ctx context.Context, name, rawTags string) error {
	objects, err := listObjects(ctx)
	if err != nil {
		return err
	}
	want := strings.Split(rawTags, ",")
	for _, object := range objects {
		if object["id"] != name {
			continue
		}
		actual, ok := object["tags"].([]any)
		if !ok {
			return fmt.Errorf("object %q tags are not an array", name)
		}
		if len(actual) != len(want) {
			return fmt.Errorf("object %q tags=%v want=%v", name, actual, want)
		}
		for i := range want {
			if actual[i] != want[i] {
				return fmt.Errorf("object %q tags=%v want=%v", name, actual, want)
			}
		}
		return nil
	}
	return fmt.Errorf("object %q not found", name)
}

// objectPathHasClassify verifies the complete time, classify, and object path shape.
func objectPathHasClassify(ctx context.Context, name, classify string) error {
	objects, err := listObjects(ctx)
	if err != nil {
		return err
	}
	classifySegments := strings.Split(classify, "/")
	for i := range classifySegments {
		classifySegments[i] = regexp.QuoteMeta(classifySegments[i])
	}
	pattern := `^\d{4}/\d{4}/\d{4}/` + strings.Join(classifySegments, `/`) + `/` + regexp.QuoteMeta(name) + `$`
	matcher := regexp.MustCompile(pattern)
	for _, object := range objects {
		if object["id"] != name {
			continue
		}
		path, ok := object["path"].(string)
		if !ok || !matcher.MatchString(path) {
			return fmt.Errorf("path %q does not match expected time/classify/object shape for %q", path, classify)
		}
		return nil
	}
	return fmt.Errorf("object %q not found", name)
}

// objectIsActive verifies an object through the public show command.
func objectIsActive(ctx context.Context, name string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	runCLI(ctx, state, []string{"show", name}, strings.NewReader(""))
	if state.result.code != 0 || !strings.Contains(string(state.result.stdout), "Status:        active") {
		return fmt.Errorf("object %s is not active: code=%d stderr=%q stdout=%q", name, state.result.code, state.result.stderr, state.result.stdout)
	}
	return nil
}

// deleteObjectRepeated transitions an object through the requested delete lifecycle steps.
func deleteObjectRepeated(ctx context.Context, name, count string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	runs := 0
	switch count {
	case "once":
		runs = 1
	case "twice":
		runs = 2
	default:
		return fmt.Errorf("unsupported delete count %q", count)
	}
	for i := 0; i < runs; i++ {
		runCLI(ctx, state, []string{"delete", name}, strings.NewReader(""))
		if state.result.code != 0 {
			return fmt.Errorf("delete %s run %d failed: stderr=%q", name, i+1, state.result.stderr)
		}
	}
	return nil
}

// jsonObjectIncludingDeletedMatches verifies metadata using the public include-deleted list option.
func jsonObjectIncludingDeletedMatches(ctx context.Context, name, description, status string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	runCLI(ctx, state, []string{"list", "--include-deleted", "--format", "json"}, strings.NewReader(""))
	if state.result.code != 0 {
		return fmt.Errorf("list including deleted failed: %s", state.result.stderr)
	}
	var objects []map[string]any
	if err := json.Unmarshal(state.result.stdout, &objects); err != nil {
		return fmt.Errorf("decode include-deleted list JSON: %w", err)
	}
	for _, object := range objects {
		if object["id"] == name {
			if object["description"] != description || object["status"] != status {
				return fmt.Errorf("object %q has description=%v status=%v", name, object["description"], object["status"])
			}
			return nil
		}
	}
	return fmt.Errorf("object %q not found in include-deleted JSON list", name)
}

// defaultListContains verifies the default list through structured JSON.
func defaultListContains(ctx context.Context, name string) error {
	objects, err := listObjects(ctx)
	if err != nil {
		return err
	}
	for _, object := range objects {
		if object["id"] == name {
			return nil
		}
	}
	return fmt.Errorf("default list did not contain %s", name)
}

// TestBDDHelpersCompile verifies the executable setup remains available.
func TestBDDHelpersCompile(t *testing.T) {
	if suiteBinary == "" {
		t.Fatal("BDD binary was not initialized")
	}
	if _, err := os.Stat(suiteBinary); err != nil {
		t.Fatalf("BDD binary missing: %v", err)
	}
}

// givenIsolatedStore verifies that the scenario hook created an isolated root.
func givenIsolatedStore(ctx context.Context) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	if state.dataRoot == "" || !strings.HasPrefix(state.dataRoot, state.root+string(os.PathSeparator)) {
		return fmt.Errorf("scenario data root is not isolated: %s", state.dataRoot)
	}
	return nil
}

// listOutputIDs decodes the current list or search result and returns IDs in output order.
func listOutputIDs(ctx context.Context, format string) ([]string, []map[string]any, error) {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return nil, nil, err
	}
	var objects []map[string]any
	switch format {
	case "json":
		err = json.Unmarshal(state.result.stdout, &objects)
	case "yaml":
		err = yaml.Unmarshal(state.result.stdout, &objects)
	default:
		return nil, nil, fmt.Errorf("unsupported assertion format %q", format)
	}
	if err != nil {
		return nil, nil, fmt.Errorf("decode %s output: %w", format, err)
	}
	ids := make([]string, 0, len(objects))
	for _, object := range objects {
		id, ok := object["id"].(string)
		if !ok {
			return nil, nil, fmt.Errorf("decoded %s object has non-string id", format)
		}
		ids = append(ids, id)
	}
	return ids, objects, nil
}

// listOutputHasIDs verifies exact structured result IDs in their returned order.
func listOutputHasIDs(ctx context.Context, format, rawIDs string) error {
	actual, _, err := listOutputIDs(ctx, format)
	if err != nil {
		return err
	}
	want := strings.Split(rawIDs, ",")
	if len(want) == 1 && want[0] == "" {
		want = nil
	}
	if len(actual) != len(want) {
		return fmt.Errorf("%s result IDs=%v want=%v", format, actual, want)
	}
	for i := range want {
		if actual[i] != want[i] {
			return fmt.Errorf("%s result IDs=%v want=%v", format, actual, want)
		}
	}
	return nil
}

// listOutputHasTimeOrder verifies each returned path has a non-increasing or non-decreasing time prefix.
func listOutputHasTimeOrder(ctx context.Context, format, order string) error {
	_, objects, err := listOutputIDs(ctx, format)
	if err != nil {
		return err
	}
	previous := ""
	for _, object := range objects {
		path, ok := object["path"].(string)
		if !ok || len(strings.Split(path, "/")) < 4 {
			return fmt.Errorf("%s result has invalid object path %v", format, object["path"])
		}
		parts := strings.Split(path, "/")
		key := strings.Join(parts[:3], "/")
		if previous != "" {
			if order == "asc" && key < previous {
				return fmt.Errorf("%s result is not ascending: %q before %q", format, previous, key)
			}
			if order == "desc" && key > previous {
				return fmt.Errorf("%s result is not descending: %q before %q", format, previous, key)
			}
		}
		previous = key
	}
	return nil
}

// listOutputContainsAllTags verifies that a structurally decoded result contains the expected IDs.
func listOutputContainsAllTags(ctx context.Context, format, rawIDs string) error {
	actual, _, err := listOutputIDs(ctx, format)
	if err != nil {
		return err
	}
	want := strings.Split(rawIDs, ",")
	set := make(map[string]bool, len(actual))
	for _, id := range actual {
		set[id] = true
	}
	for _, id := range want {
		if !set[id] {
			return fmt.Errorf("%s result IDs=%v missing %q", format, actual, id)
		}
	}
	return nil
}

// jsonObjectDataRefMatchesPath verifies that the public data reference resolves to the same moved location as path.
func jsonObjectDataRefMatchesPath(ctx context.Context, name, classify string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	objects, err := listObjects(ctx)
	if err != nil {
		return err
	}
	classifySegments := strings.Split(classify, "/")
	for _, object := range objects {
		if object["id"] != name {
			continue
		}
		path, ok := object["path"].(string)
		if !ok {
			return fmt.Errorf("object %q has non-string public path", name)
		}
		parts := strings.Split(path, "/")
		if len(parts) < 4 {
			return fmt.Errorf("object %q has invalid public path %q", name, path)
		}
		wantPath := strings.Join(append(parts[:3], append(classifySegments, name)...), "/")
		if path != wantPath {
			return fmt.Errorf("object %q public path=%q want=%q", name, path, wantPath)
		}
		dataRef, ok := object["data_ref"].(string)
		if !ok {
			return fmt.Errorf("object %q has non-string public data_ref", name)
		}
		wantRef := filepath.Join(state.dataRoot, filepath.FromSlash(wantPath))
		if dataRef != wantRef {
			return fmt.Errorf("object %q public data_ref=%q want=%q", name, dataRef, wantRef)
		}
		return nil
	}
	return fmt.Errorf("object %q not found", name)
}

// jsonObjectPathClassifyMatches verifies the complete public path shape for a classify path.
func jsonObjectPathClassifyMatches(ctx context.Context, name, classify string) error {
	return objectPathHasClassify(ctx, name, classify)
}

// addClassifyTags writes a test classify tag file using the object's public path.
func addClassifyTags(ctx context.Context, name, classify, rawTags string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	objects, err := listObjects(ctx)
	if err != nil {
		return err
	}
	var objectPath string
	for _, object := range objects {
		if object["id"] == name {
			objectPath, _ = object["path"].(string)
			break
		}
	}
	if objectPath == "" {
		return fmt.Errorf("object %q not found in public list", name)
	}
	parts := strings.Split(objectPath, "/")
	classifyParts := strings.Split(classify, "/")
	if len(parts) < 4+len(classifyParts) {
		return fmt.Errorf("object %q path %q is shorter than classify %q", name, objectPath, classify)
	}
	classifyPath := append([]string{}, parts[:3]...)
	classifyPath = append(classifyPath, classifyParts...)
	path := filepath.Join(append([]string{state.dataRoot}, classifyPath...)...)
	if err := os.MkdirAll(path, 0o755); err != nil {
		return fmt.Errorf("create classify directory: %w", err)
	}
	file := filepath.Join(path, filepath.Base(path)+".tags")
	if err := os.WriteFile(file, []byte(strings.ReplaceAll(rawTags, ",", "\n")+"\n"), 0o644); err != nil {
		return fmt.Errorf("write classify tags: %w", err)
	}
	return nil
}

// recordPublicMetadata saves identity and creation metadata obtained from public list output.
func recordPublicMetadata(ctx context.Context, name string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	objects, err := listObjects(ctx)
	if err != nil {
		return err
	}
	for _, object := range objects {
		if object["id"] != name {
			continue
		}
		state.recordedMetadata = map[string]any{
			"id": object["id"], "name": object["name"], "created_at": object["created_at"],
		}
		return nil
	}
	return fmt.Errorf("object %q not found in public list", name)
}

// recordedPublicMetadataMatches verifies identity and creation metadata after a move.
func recordedPublicMetadataMatches(ctx context.Context, name string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	if state.recordedMetadata == nil {
		return fmt.Errorf("no recorded metadata for object %q", name)
	}
	recorded := state.recordedMetadata
	objects, err := listObjects(ctx)
	if err != nil {
		return err
	}
	for _, object := range objects {
		if object["id"] != name {
			continue
		}
		for _, key := range []string{"id", "name", "created_at"} {
			if object[key] != recorded[key] {
				return fmt.Errorf("moved object %q changed %s: before=%v after=%v", name, key, recorded[key], object[key])
			}
		}
		return nil
	}
	return fmt.Errorf("object %q not found after move", name)
}

// putGeneratedArchive writes a Go-generated tar archive through the public CLI.
func putGeneratedArchive(ctx context.Context, name, markerMode string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	archivePath := filepath.Join(state.root, "input.tar")
	archiveFile, err := os.Create(archivePath)
	if err != nil {
		return fmt.Errorf("create generated archive: %w", err)
	}
	tw := tar.NewWriter(archiveFile)
	if markerMode == "with marker" {
		content := []byte("replacement markdown")
		if err := tw.WriteHeader(&tar.Header{Name: name + ".md", Mode: 0o644, Size: int64(len(content)), Typeflag: tar.TypeReg}); err != nil {
			_ = archiveFile.Close()
			return fmt.Errorf("write generated marker header: %w", err)
		}
		if _, err := tw.Write(content); err != nil {
			_ = archiveFile.Close()
			return fmt.Errorf("write generated marker: %w", err)
		}
	}
	content := []byte("archive extra content")
	if err := tw.WriteHeader(&tar.Header{Name: "archive-extra.txt", Mode: 0o644, Size: int64(len(content)), Typeflag: tar.TypeReg}); err != nil {
		_ = archiveFile.Close()
		return fmt.Errorf("write generated extra header: %w", err)
	}
	if _, err := tw.Write(content); err != nil {
		_ = archiveFile.Close()
		return fmt.Errorf("write generated extra: %w", err)
	}
	if err := tw.Close(); err != nil {
		_ = archiveFile.Close()
		return fmt.Errorf("close generated tar: %w", err)
	}
	if err := archiveFile.Close(); err != nil {
		return fmt.Errorf("close generated archive: %w", err)
	}
	runCLI(ctx, state, []string{"put-archive", name, archivePath}, strings.NewReader(""))
	return nil
}
