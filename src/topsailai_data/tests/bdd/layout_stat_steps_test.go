package bdd

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/cucumber/godog"
	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// registerLayoutStatSteps registers steps for store layout, statistics,
// binary fidelity, and archive-based recovery.
func registerLayoutStatSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^the store layout is initialized$`, storeLayoutInitialized)
	ctx.Step(`^a store root containing an unrelated file "([^"]+)"$`, storeRootWithUnrelatedFile)
	ctx.Step(`^object "([^"]+)" metadata is stored under a hashed directory with a separate tags file$`, metadataHashedWithSeparateTags)
	ctx.Step(`^the data reference of object "([^"]+)" is relative to the object tree$`, dataRefIsRelative)
	ctx.Step(`^a classify tag file with tag "([^"]+)" beside object "([^"]+)"$`, classifyTagFileBesideObject)
	ctx.Step(`^object "([^"]+)" has no tags$`, objectHasNoTags)
	ctx.Step(`^the stat of object "([^"]+)" reports read count (\d+) and write count (\d+)$`, statReportsCounts)
	ctx.Step(`^I record the stat of object "([^"]+)"$`, recordStat)
	ctx.Step(`^the stat of object "([^"]+)" is unchanged$`, statIsUnchanged)
	ctx.Step(`^the stat top ranking by (read|write) in (asc|desc) order starts with "([^"]+)"$`, statTopStartsWith)
	ctx.Step(`^the JSON list with stat contains object "([^"]+)" with read count (\d+) and write count (\d+)$`, jsonListWithStatContains)
	ctx.Step(`^a scenario binary file "([^"]+)" with hex bytes "([^"]+)"$`, scenarioBinaryFile)
	ctx.Step(`^I put scenario file "([^"]+)" into object "([^"]+)" as "([^"]+)"$`, putScenarioFileIntoObject)
	ctx.Step(`^object "([^"]+)" file "([^"]+)" equals scenario binary file "([^"]+)"$`, objectFileEqualsScenarioBinary)
	ctx.Step(`^a scenario archive "([^"]+)" containing file "([^"]+)" with content "([^"]*)"$`, scenarioArchiveWithFile)
	ctx.Step(`^I recover object "([^"]+)" from scenario archive "([^"]+)"$`, recoverFromScenarioArchive)
}

// layoutMarkerView mirrors the on-disk layout marker for assertions.
type layoutMarkerView struct {
	Layout        string `json:"layout"`
	LayoutVersion int    `json:"layout_version"`
	SchemaVersion int    `json:"schema_version"`
}

// storeLayoutInitialized verifies the marker and the sibling object/meta trees.
func storeLayoutInitialized(ctx context.Context) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	data, err := os.ReadFile(filepath.Join(state.dataRoot, "topsailai_data.json"))
	if err != nil {
		return fmt.Errorf("read layout marker: %w", err)
	}
	var marker layoutMarkerView
	if err := json.Unmarshal(data, &marker); err != nil {
		return fmt.Errorf("decode layout marker: %w", err)
	}
	if marker.Layout != "object-meta" || marker.LayoutVersion != 1 || marker.SchemaVersion < 1 {
		return fmt.Errorf("unexpected layout marker %+v", marker)
	}
	for _, name := range []string{"object", "meta"} {
		info, err := os.Lstat(filepath.Join(state.dataRoot, name))
		if err != nil {
			return fmt.Errorf("inspect layout tree %q: %w", name, err)
		}
		if !info.IsDir() {
			return fmt.Errorf("layout tree %q is not a directory", name)
		}
	}
	return nil
}

// storeRootWithUnrelatedFile makes the store root non-empty before initialization.
func storeRootWithUnrelatedFile(ctx context.Context, name string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(state.dataRoot, name), []byte("unrelated\n"), 0o644)
}

// metadataHashedWithSeparateTags verifies identity-addressed metadata storage.
func metadataHashedWithSeparateTags(ctx context.Context, name string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	layout, err := local.NewStoreLayout(state.dataRoot)
	if err != nil {
		return err
	}
	metaPath, err := layout.ObjectMetaPath(models.ObjectID(name))
	if err != nil {
		return err
	}
	record, err := os.ReadFile(filepath.Join(metaPath, "metadata.json"))
	if err != nil {
		return fmt.Errorf("read metadata record: %w", err)
	}
	if strings.Contains(string(record), `"tags"`) {
		return fmt.Errorf("metadata record must not carry tags: %s", record)
	}
	info, err := os.Lstat(filepath.Join(metaPath, "tags"))
	if err != nil {
		return fmt.Errorf("inspect separate tags file: %w", err)
	}
	if !info.Mode().IsRegular() {
		return fmt.Errorf("tags authority must be a regular file")
	}
	return nil
}

// dataRefIsRelative verifies the reference is canonical and resolves under object/.
func dataRefIsRelative(ctx context.Context, name string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	objects, err := listObjects(ctx)
	if err != nil {
		return err
	}
	ref := ""
	for _, object := range objects {
		if object["id"] == name {
			ref, _ = object["data_ref"].(string)
			break
		}
	}
	if ref == "" {
		return fmt.Errorf("object %q has no data reference", name)
	}
	if filepath.IsAbs(ref) || strings.Contains(ref, "..") {
		return fmt.Errorf("data reference %q is not relative", ref)
	}
	layout, err := local.NewStoreLayout(state.dataRoot)
	if err != nil {
		return err
	}
	dir, err := layout.ResolveObjectRef(ref)
	if err != nil {
		return err
	}
	info, err := os.Lstat(dir)
	if err != nil {
		return fmt.Errorf("inspect payload directory: %w", err)
	}
	if !info.IsDir() {
		return fmt.Errorf("payload reference %q does not resolve to a directory", ref)
	}
	return nil
}

// classifyTagFileBesideObject writes a classify tag file next to the object folder.
func classifyTagFileBesideObject(ctx context.Context, tag, name string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	objects, err := listObjects(ctx)
	if err != nil {
		return err
	}
	ref := ""
	for _, object := range objects {
		if object["id"] == name {
			ref, _ = object["data_ref"].(string)
			break
		}
	}
	if ref == "" {
		return fmt.Errorf("object %q has no data reference", name)
	}
	layout, err := local.NewStoreLayout(state.dataRoot)
	if err != nil {
		return err
	}
	dir, err := layout.ResolveObjectRef(ref)
	if err != nil {
		return err
	}
	classifyDir := filepath.Dir(dir)
	path := filepath.Join(classifyDir, filepath.Base(classifyDir)+".tags")
	return os.WriteFile(path, []byte(tag+"\n"), 0o644)
}

// objectHasNoTags verifies classify tag files are not inherited.
func objectHasNoTags(ctx context.Context, name string) error {
	objects, err := listObjects(ctx)
	if err != nil {
		return err
	}
	for _, object := range objects {
		if object["id"] != name {
			continue
		}
		tags, ok := object["tags"].([]any)
		if !ok {
			return fmt.Errorf("object %q tags are not an array", name)
		}
		if len(tags) != 0 {
			return fmt.Errorf("object %q inherited tags %v", name, tags)
		}
		return nil
	}
	return fmt.Errorf("object %q not found", name)
}

// statCounts is the subset of the stat record used by assertions.
type statCounts struct {
	ReadCount  uint64 `json:"read_count"`
	WriteCount uint64 `json:"write_count"`
}

// readStatCounts runs the stat command and decodes the counters.
func readStatCounts(ctx context.Context, name string) (statCounts, string, error) {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return statCounts{}, "", err
	}
	runCLI(ctx, state, []string{"stat", name, "--format", "json"}, strings.NewReader(""))
	if state.result.code != 0 {
		return statCounts{}, "", fmt.Errorf("stat %q failed: %s", name, state.result.stderr)
	}
	var counts statCounts
	if err := json.Unmarshal(state.result.stdout, &counts); err != nil {
		return statCounts{}, "", fmt.Errorf("decode stat %q: %w", name, err)
	}
	return counts, string(state.result.stdout), nil
}

// statReportsCounts verifies both counters for one object.
func statReportsCounts(ctx context.Context, name, readCount, writeCount string) error {
	counts, _, err := readStatCounts(ctx, name)
	if err != nil {
		return err
	}
	wantRead, wantWrite := uint64(0), uint64(0)
	if _, err := fmt.Sscanf(readCount, "%d", &wantRead); err != nil {
		return err
	}
	if _, err := fmt.Sscanf(writeCount, "%d", &wantWrite); err != nil {
		return err
	}
	if counts.ReadCount != wantRead || counts.WriteCount != wantWrite {
		return fmt.Errorf("object %q stat read=%d write=%d want read=%d write=%d", name, counts.ReadCount, counts.WriteCount, wantRead, wantWrite)
	}
	return nil
}

// recordStat stores the current stat payload for a later comparison.
func recordStat(ctx context.Context, name string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	_, raw, err := readStatCounts(ctx, name)
	if err != nil {
		return err
	}
	state.recordedStat = raw
	return nil
}

// statIsUnchanged compares the current stat payload with the recorded one.
func statIsUnchanged(ctx context.Context, name string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	if state.recordedStat == "" {
		return fmt.Errorf("no recorded stat for %q", name)
	}
	_, raw, err := readStatCounts(ctx, name)
	if err != nil {
		return err
	}
	if raw != state.recordedStat {
		return fmt.Errorf("stat for %q changed: before=%s after=%s", name, state.recordedStat, raw)
	}
	return nil
}

// statTopStartsWith verifies the first ranked row of the current stat top output.
func statTopStartsWith(ctx context.Context, by, order, name string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	if state.result.code != 0 {
		return fmt.Errorf("stat top failed: %s", state.result.stderr)
	}
	var rows []struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(state.result.stdout, &rows); err != nil {
		return fmt.Errorf("decode stat top %s/%s: %w", by, order, err)
	}
	if len(rows) == 0 {
		return fmt.Errorf("stat top %s/%s returned no rows", by, order)
	}
	if rows[0].ID != name {
		return fmt.Errorf("stat top %s/%s first row is %q want %q", by, order, rows[0].ID, name)
	}
	return nil
}

// jsonListWithStatContains verifies attached counters in list output.
func jsonListWithStatContains(ctx context.Context, name, readCount, writeCount string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	if state.result.code != 0 {
		return fmt.Errorf("list with stat failed: %s", state.result.stderr)
	}
	var objects []map[string]any
	if err := json.Unmarshal(state.result.stdout, &objects); err != nil {
		return fmt.Errorf("decode list with stat: %w", err)
	}
	wantRead, wantWrite := uint64(0), uint64(0)
	if _, err := fmt.Sscanf(readCount, "%d", &wantRead); err != nil {
		return err
	}
	if _, err := fmt.Sscanf(writeCount, "%d", &wantWrite); err != nil {
		return err
	}
	for _, object := range objects {
		if object["id"] != name {
			continue
		}
		gotRead, okRead := object["read_count"].(float64)
		gotWrite, okWrite := object["write_count"].(float64)
		if !okRead || !okWrite {
			return fmt.Errorf("object %q has no attached stat fields", name)
		}
		if uint64(gotRead) != wantRead || uint64(gotWrite) != wantWrite {
			return fmt.Errorf("object %q attached stat read=%v write=%v want read=%d write=%d", name, gotRead, gotWrite, wantRead, wantWrite)
		}
		return nil
	}
	return fmt.Errorf("object %q not found in list with stat", name)
}

// scenarioBinaryFile writes raw bytes decoded from a hex string.
func scenarioBinaryFile(ctx context.Context, relative, hexBytes string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	data, err := hex.DecodeString(hexBytes)
	if err != nil {
		return fmt.Errorf("decode hex bytes: %w", err)
	}
	path := filepath.Join(state.root, relative)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}

// putScenarioFileIntoObject writes a scenario file into an object through put.
func putScenarioFileIntoObject(ctx context.Context, relative, name, dest string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	runCLI(ctx, state, []string{"put", name, dest, "--from", filepath.Join(state.root, relative)}, strings.NewReader(""))
	return nil
}

// objectFileEqualsScenarioBinary compares stored bytes with a scenario file.
func objectFileEqualsScenarioBinary(ctx context.Context, name, path, relative string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	want, err := os.ReadFile(filepath.Join(state.root, relative))
	if err != nil {
		return fmt.Errorf("read scenario binary file: %w", err)
	}
	runCLI(ctx, state, []string{"get", name, path}, strings.NewReader(""))
	if state.result.code != 0 {
		return fmt.Errorf("get %s from %q failed: %s", path, name, state.result.stderr)
	}
	if !bytes.Equal(state.result.stdout, want) {
		return fmt.Errorf("object %q file %q bytes differ: got %d bytes want %d bytes", name, path, len(state.result.stdout), len(want))
	}
	return nil
}

// scenarioArchiveWithFile builds a tar archive outside the object tree.
func scenarioArchiveWithFile(ctx context.Context, archive, file, content string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	return writeTarArchive(filepath.Join(state.root, archive), map[string]string{file: unescapeContent(content)})
}

// recoverFromScenarioArchive restores a deleted object from an external archive.
func recoverFromScenarioArchive(ctx context.Context, name, archive string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	runCLI(ctx, state, []string{"recover", name, "--from", filepath.Join(state.root, archive)}, strings.NewReader(""))
	return nil
}
