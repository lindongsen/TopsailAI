package bdd

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"

	"github.com/cucumber/godog"
)

var (
	suiteBinary string
	projectRoot string
)

func TestMain(m *testing.M) {
	_, sourceFile, _, ok := runtime.Caller(0)
	if !ok {
		os.Exit(1)
	}
	projectRoot = filepath.Clean(filepath.Join(filepath.Dir(sourceFile), "..", ".."))
	root := filepath.Join(projectRoot, ".tmp", "bdd")
	if err := os.MkdirAll(filepath.Join(root, "bin"), 0o755); err != nil {
		os.Exit(1)
	}
	if err := os.MkdirAll(filepath.Join(root, "scenarios"), 0o755); err != nil {
		os.Exit(1)
	}
	suiteBinary = filepath.Join(root, "bin", "topsailai-data")
	cmd := exec.Command("go", "build", "-o", suiteBinary, "./cmd/topsailai-data")
	cmd.Dir = projectRoot
	if output, err := cmd.CombinedOutput(); err != nil {
		_, _ = os.Stderr.Write(output)
		os.Exit(1)
	}
	os.Exit(m.Run())
}

func TestBDD(t *testing.T) {
	runBDD(t, "")
}

func TestBDDSmoke(t *testing.T) {
	runBDD(t, "@smoke")
}

func runBDD(t *testing.T, tags string) {
	t.Helper()
	suite := godog.TestSuite{
		Name: "topsailai-data-bdd",
		ScenarioInitializer: func(ctx *godog.ScenarioContext) {
			registerSteps(ctx)
		},
		Options: &godog.Options{
			Format:   "progress",
			NoColors: true,
			Paths:    []string{"features"},
			Tags:     tags,
			Output:   os.Stdout,
		},
	}
	if status := suite.Run(); status != 0 {
		t.Fail()
	}
}

func registerSteps(ctx *godog.ScenarioContext) {
	ctx.Before(func(ctx context.Context, sc *godog.Scenario) (context.Context, error) {
		return newScenarioContext(ctx, sc)
	})
	ctx.After(func(ctx context.Context, sc *godog.Scenario, err error) (context.Context, error) {
		return cleanupScenario(ctx, sc, err)
	})
	ctx.Step(`^an isolated topsailai-data store$`, givenIsolatedStore)
	ctx.Step(`^I create object "([^"]+)" from fixture "([^"]+)"$`, createFromFixture)
	ctx.Step(`^I create object "([^"]+)" from fixture "([^"]+)" with description "([^"]+)", tags "([^"]*)", and classify "([^"]*)"$`, createConfiguredFromFixture)
	ctx.Step(`^I create object "([^"]+)" from fixture "([^"]+)" with description "([^"]+)"$`, func(ctx context.Context, name, fixture, description string) error {
		return createConfiguredFromFixture(ctx, name, fixture, description, "", "")
	})
	ctx.Step(`^I create object "([^"]+)" from fixture "([^"]+)" with description "([^"]+)" and classify "([^"]+)"$`, func(ctx context.Context, name, fixture, description, classify string) error {
		return createConfiguredFromFixture(ctx, name, fixture, description, "", classify)
	})
	ctx.Step(`^I create object "([^"]+)" from fixture "([^"]+)" with description "([^"]+)" and tags "([^"]+)" and classify "([^"]+)"$`, func(ctx context.Context, name, fixture, description, tags, classify string) error {
		return createConfiguredFromFixture(ctx, name, fixture, description, tags, classify)
	})
	ctx.Step(`^I create object "([^"]+)" from stdin with description "([^"]+)" and content "([^"]+)"$`, createFromStdin)
	ctx.Step(`^I run topsailai-data with arguments:$`, runArguments)
	ctx.Step(`^I wait for a new time-prefix minute after "([^"]+)"$`, waitForNewTimePrefixMinute)
	ctx.Step(`^the sort fixtures have distinct public time-prefix keys$`, sortFixturesHaveDistinctTimePrefixes)
	ctx.Step(`^I delete object "([^"]+)" (once|twice) times$`, deleteObjectRepeated)
	ctx.Step(`^the command succeeds$`, commandSucceeds)
	ctx.Step(`^the command fails$`, commandFails)
	ctx.Step(`^the command fails with "([^"]+)"$`, commandFailsWith)
	ctx.Step(`^stdout contains "([^"]+)"$`, stdoutContains)
	ctx.Step(`^stdout does not contain "([^"]+)"$`, stdoutDoesNotContain)
	ctx.Step(`^the default list contains "([^"]+)"$`, defaultListContains)
	ctx.Step(`^the JSON list contains object "([^"]+)" with description "([^"]*)" and status "([^"]+)"$`, jsonObjectMatches)
	ctx.Step(`^the YAML list contains object "([^"]+)" with description "([^"]*)" and status "([^"]+)"$`, yamlObjectMatches)
	ctx.Step(`^the JSON list contains object "([^"]+)" with tags "([^"]*)"$`, jsonObjectTagsMatches)
	ctx.Step(`^the JSON list including deleted objects contains object "([^"]+)" with description "([^"]*)" and status "([^"]+)"$`, jsonObjectIncludingDeletedMatches)
	ctx.Step(`^the object "([^"]+)" path has classify "([^"]+)"$`, objectPathHasClassify)
	ctx.Step(`^I create object "([^"]+)" from fixture "([^"]+)" with description "([^"]+)" and tags "([^"]+)"$`, func(ctx context.Context, name, fixture, description, tags string) error {
		return createConfiguredFromFixture(ctx, name, fixture, description, tags, "")
	})
	ctx.Step(`^the (JSON|YAML) list has exactly IDs "([^"]*)"$`, func(ctx context.Context, format, ids string) error {
		return listOutputHasIDs(ctx, strings.ToLower(format), ids)
	})
	ctx.Step(`^the (JSON|YAML) list has exactly (\d+) object(s?)$`, func(ctx context.Context, format, count, _ string) error {
		actual, _, err := listOutputIDs(ctx, strings.ToLower(format))
		if err != nil {
			return err
		}
		want, parseErr := strconv.Atoi(count)
		if parseErr != nil {
			return parseErr
		}
		if len(actual) != want {
			return fmt.Errorf("%s result has %d objects, want %d", format, len(actual), want)
		}
		return nil
	})
	ctx.Step(`^the (JSON|YAML) list has (ascending|descending) time-prefix order$`, func(ctx context.Context, format, order string) error {
		return listOutputHasTimeOrder(ctx, strings.ToLower(format), map[string]string{"ascending": "asc", "descending": "desc"}[order])
	})
	ctx.Step(`^the (JSON|YAML) search result contains exactly IDs "([^"]*)"$`, func(ctx context.Context, format, ids string) error {
		return listOutputHasIDs(ctx, strings.ToLower(format), ids)
	})
	ctx.Step(`^the (JSON|YAML) search result contains IDs "([^"]*)"$`, func(ctx context.Context, format, ids string) error {
		return listOutputContainsAllTags(ctx, strings.ToLower(format), ids)
	})
	ctx.Step(`^the (JSON|YAML) search result has exactly IDs "([^"]*)"$`, func(ctx context.Context, format, ids string) error {
		return listOutputHasIDs(ctx, strings.ToLower(format), ids)
	})
	ctx.Step(`^I add classify tags "([^"]+)" to "([^"]+)" at level "([^"]+)"$`, func(ctx context.Context, tags, name, classify string) error {
		return addClassifyTags(ctx, name, classify, tags)
	})
	ctx.Step(`^I record public metadata for "([^"]+)"$`, recordPublicMetadata)
	ctx.Step(`^the JSON list contains object "([^"]+)" with path classify "([^"]+)"$`, jsonObjectPathClassifyMatches)
	ctx.Step(`^the JSON list contains object "([^"]+)" with data reference matching path classify "([^"]+)"$`, jsonObjectDataRefMatchesPath)
	ctx.Step(`^I put a generated archive (with marker|without marker) into object "([^"]+)"$`, func(ctx context.Context, markerMode, name string) error {
		return putGeneratedArchive(ctx, name, markerMode)
	})
	ctx.Step(`^the object "([^"]+)" retains recorded identity and creation metadata$`, recordedPublicMetadataMatches)
}
