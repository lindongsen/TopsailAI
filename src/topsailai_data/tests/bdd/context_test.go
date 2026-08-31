package bdd

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/cucumber/godog"
)

type scenarioContext struct {
	root             string
	dataRoot         string
	result           commandResult
	recordedMetadata map[string]any
}

type commandResult struct {
	stdout []byte
	stderr []byte
	err    error
	code   int
}

func scenarioFrom(ctx context.Context) (*scenarioContext, error) {
	value := ctx.Value(scenarioKey{})
	state, ok := value.(*scenarioContext)
	if !ok {
		return nil, fmt.Errorf("missing BDD scenario context")
	}
	return state, nil
}

type scenarioKey struct{}

func newScenarioContext(ctx context.Context, _ *godog.Scenario) (context.Context, error) {
	base := filepath.Join(projectRoot, ".tmp", "bdd", "scenarios")
	root, err := os.MkdirTemp(base, "scenario-")
	if err != nil {
		return ctx, err
	}
	dataRoot := filepath.Join(root, "data")
	if err := os.MkdirAll(dataRoot, 0o755); err != nil {
		return ctx, err
	}
	return context.WithValue(ctx, scenarioKey{}, &scenarioContext{root: root, dataRoot: dataRoot}), nil
}

func cleanupScenario(ctx context.Context, _ *godog.Scenario, _ error) (context.Context, error) {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return ctx, err
	}
	base := filepath.Join(projectRoot, ".tmp", "bdd", "scenarios") + string(os.PathSeparator)
	if !strings.HasPrefix(state.root, base) {
		return ctx, fmt.Errorf("refusing cleanup outside BDD scenario root: %s", state.root)
	}
	if err := os.RemoveAll(state.root); err != nil {
		return ctx, fmt.Errorf("cleanup %s: %w", state.root, err)
	}
	fmt.Fprintf(os.Stderr, "bdd cleanup deleted %s\n", state.root)
	return ctx, nil
}
func runCLI(ctx context.Context, state *scenarioContext, args []string, input io.Reader) {
	env := make([]string, 0, len(os.Environ()))
	for _, item := range os.Environ() {
		if !strings.HasPrefix(item, "TOPSAILAI_DATA_") {
			env = append(env, item)
		}
	}
	env = append(env,
		"TOPSAILAI_DATA_ROOT="+state.dataRoot,
		"TOPSAILAI_DATA_METADATA_ADAPTER=local",
		"TOPSAILAI_DATA_ACTUAL_DATA_ADAPTER=local",
		"TOPSAILAI_DATA_INCLUDE_DELETED=0",
		"TOPSAILAI_DATA_TRACK_STAT=1",
		"TOPSAILAI_DATA_CEASED_RETENTION_DAYS=30",
	)
	cmd := exec.Command(suiteBinary, args...)
	cmd.Env = env
	cmd.Stdin = input
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	code := 0
	if err != nil {
		code = 1
		if exitErr, ok := err.(*exec.ExitError); ok {
			code = exitErr.ExitCode()
		}
	}
	state.result = commandResult{stdout: stdout.Bytes(), stderr: stderr.Bytes(), err: err, code: code}
}

func fixturePath(_ *scenarioContext, name string) string {
	return filepath.Join(projectRoot, "tests", "bdd", "fixtures", name)
}
func requireState(t *testing.T, ctx context.Context) *scenarioContext {
	t.Helper()
	state, err := scenarioFrom(ctx)
	if err != nil {
		t.Fatal(err)
	}
	return state
}
