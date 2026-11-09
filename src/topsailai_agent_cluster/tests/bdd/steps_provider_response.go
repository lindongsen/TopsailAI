package bdd

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/tests/harness"
)

// registerProviderResponseSteps registers the provider raw return display scenarios.
// These scenarios drive both surfaces, because the two-part output is not
// interactive-only: the standalone command renders the same receipt, and only its
// --json mode keeps the machine envelope.
func registerProviderResponseSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster with a healthy provider for the interactive REPL$`, startInteractiveCluster)
	ctx.Step(`^a real cluster whose provider fails execution$`, startInteractiveFailingCluster)
	ctx.Step(`^a session scope send is driven through the interactive REPL$`, driveInteractiveSend)
	ctx.Step(`^the interactive output shows the service receipt section$`, assertInteractiveReceiptSection)
	ctx.Step(`^the interactive output shows the provider raw return section$`, assertInteractiveProviderSection)
	ctx.Step(`^the interactive output carries the provider document verbatim$`, assertProviderDocumentVerbatim)
	ctx.Step(`^the service receipt section appears before the provider raw return section$`, assertReceiptBeforeProvider)
	ctx.Step(`^the interactive output shows the provider diagnostic$`, assertInteractiveProviderDiagnostic)
	ctx.Step(`^a session scope btw is driven through the standalone command$`, driveStandaloneContextInject)
	ctx.Step(`^a session scope btw is driven through the standalone command with --json$`, driveStandaloneContextInjectJSON)
	ctx.Step(`^the standalone output shows the service receipt section$`, assertStandaloneReceiptSection)
	ctx.Step(`^the standalone output shows the provider raw return section$`, assertStandaloneProviderSection)
	ctx.Step(`^the standalone output carries the provider document verbatim$`, assertStandaloneProviderDocumentVerbatim)
	ctx.Step(`^the standalone output is one parseable JSON document$`, assertStandaloneJSONDocument)
	ctx.Step(`^the JSON document carries the provider document as a string$`, assertStandaloneJSONProviderDocument)
}

// interactiveSendScript navigates to the first session row, sends one literal
// message and quits. An explicit send submits directly, so no answer line is
// needed. Row navigation is used because the startup list already rendered the
// visible numbering.
const interactiveSendScript = "cd 1\nsend bdd provider response probe\nquit\n"

// startInteractiveCluster starts a real cluster whose provider succeeds.
//
// The generic fixture adapter's default capability list omits context.inject, so
// the scenario declares the operations it drives. The default is a production
// value, so it is replaced here rather than widened for every deployment.
func startInteractiveCluster() error {
	return startInteractiveClusterWith(harness.FaultInjection{
		AdvertisedCapabilities: []string{"message.send", "context.inject", "execution.interrupt", "agent.stop"},
	})
}

// startInteractiveFailingCluster starts a real cluster whose provider fails
// execution while keeping discovery healthy, so the session is still visible.
func startInteractiveFailingCluster() error {
	return startInteractiveClusterWith(harness.FaultInjection{
		ProviderFailAdapterID:  "fixture-main",
		AdvertisedCapabilities: []string{"message.send", "context.inject", "execution.interrupt", "agent.stop"},
	})
}

// startInteractiveClusterWith starts the real cluster and builds the CLI binary.
func startInteractiveClusterWith(faults harness.FaultInjection) error {
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	world := activeScenario.world
	if err := world.StartRealCluster(faults); err != nil {
		return err
	}
	activeScenario.realCluster = world.realCluster
	if _, err := activeScenario.realCluster.BuildTUI(activeTest); err != nil {
		return fmt.Errorf("build CLI: %w", err)
	}
	return nil
}

// driveInteractiveSend runs the scripted REPL session and records its output.
// The wait budget is shortened so a command whose effect stays unknown does not
// consume the default ten second local wait.
func driveInteractiveSend() error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	stdout, stderr, code, err := activeScenario.realCluster.RunTUIInteractive(interactiveSendScript, "--wait-timeout-ms", "3000")
	activeScenario.lastBody = []byte(stdout)
	activeScenario.lastStatus = code
	if err != nil && code == 0 {
		return fmt.Errorf("run interactive REPL: %v; stderr=%s", err, stderr)
	}
	if code != 0 {
		return fmt.Errorf("interactive REPL exit code=%d stderr=%s output=%s", code, stderr, stdout)
	}
	return nil
}

// interactiveOutput returns the recorded REPL output.
func interactiveOutput() string {
	return string(activeScenario.lastBody)
}

// assertInteractiveReceiptSection proves this service's own receipt is rendered.
func assertInteractiveReceiptSection() error {
	text := interactiveOutput()
	for _, value := range []string{"command submitted:", "delivery_boundary:", "effect_certainty:"} {
		if !strings.Contains(text, value) {
			return fmt.Errorf("interactive output is missing the service receipt field %q: %s", value, text)
		}
	}
	return nil
}

// assertInteractiveProviderSection proves the provider's own document is rendered
// under its own labelled section, separate from this service's receipt. The
// document itself is provider-specific, so only the section and a non-empty body
// are asserted here; the verbatim content is asserted by its own step.
func assertInteractiveProviderSection() error {
	text := interactiveOutput()
	index := strings.Index(text, "provider_response:")
	if index < 0 {
		return fmt.Errorf("interactive output is missing the provider raw return section: %s", text)
	}
	body := strings.TrimSpace(text[index+len("provider_response:"):])
	if body == "" {
		return fmt.Errorf("provider raw return section is empty: %s", text)
	}
	return nil
}

// assertProviderDocumentVerbatim proves the provider's own document appears
// unmodified, so the section carries provider evidence rather than a re-rendered
// summary. The fixture provider's success document is the expected content.
func assertProviderDocumentVerbatim() error {
	text := interactiveOutput()
	if !strings.Contains(text, `"effect_certainty":"acknowledged"`) {
		return fmt.Errorf("interactive output does not carry the provider document verbatim: %s", text)
	}
	return nil
}

// assertReceiptBeforeProvider proves the two parts are ordered: this service's
// own output first, then the provider's raw return.
//
// The two surfaces announce themselves differently, so the marker is chosen from
// what the output actually carries instead of being hardcoded to one surface. The
// interactive REPL announces the submission ("command submitted:") before it
// renders the receipt, while the standalone command has no submission
// announcement and starts directly at the receipt status label ("confirmed
// result"). Both markers are this service's own output, so the earliest one that
// appears is the start of the receipt section on either surface.
func assertReceiptBeforeProvider() error {
	text := interactiveOutput()
	provider := strings.Index(text, "provider_response:")
	if provider < 0 {
		return fmt.Errorf("output is missing the provider raw return section: %s", text)
	}
	receipt := -1
	for _, marker := range []string{"command submitted:", "confirmed result"} {
		if index := strings.Index(text, marker); index >= 0 && (receipt < 0 || index < receipt) {
			receipt = index
		}
	}
	if receipt < 0 {
		return fmt.Errorf("output is missing the service receipt section: %s", text)
	}
	if receipt > provider {
		return fmt.Errorf("provider raw return appears before the service receipt: %s", text)
	}
	return nil
}

// assertInteractiveProviderDiagnostic proves a failed provider invocation still
// surfaces the provider's own diagnostic instead of discarding it.
func assertInteractiveProviderDiagnostic() error {
	text := interactiveOutput()
	if !strings.Contains(text, "fixture execution failure") {
		return fmt.Errorf("interactive output is missing the provider diagnostic: %s", text)
	}
	return nil
}

// standaloneContextInjectArgs builds the argv for one standalone btw against the
// first reported session. The generation is read from the same inventory the
// command revalidates against, so the step never guesses a target.
func standaloneContextInjectArgs() ([]string, error) {
	resourceID, err := tuiResourceID()
	if err != nil {
		return nil, err
	}
	generation, err := tuiGeneration(resourceID)
	if err != nil {
		return nil, err
	}
	if generation == "" {
		return nil, fmt.Errorf("session %q has no generation", resourceID)
	}
	return []string{"--yes", "btw", "endpoint-1", resourceID, "bdd provider response probe", generation}, nil
}

// driveStandaloneContextInject runs one standalone btw and records its output.
func driveStandaloneContextInject() error {
	return runStandaloneContextInject(false)
}

// driveStandaloneContextInjectJSON runs one standalone btw with --json.
func driveStandaloneContextInjectJSON() error {
	return runStandaloneContextInject(true)
}

// runStandaloneContextInject executes the standalone command and records the
// combined output, so a failure message shows the operator's real view.
func runStandaloneContextInject(jsonMode bool) error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	args, err := standaloneContextInjectArgs()
	if err != nil {
		return err
	}
	if jsonMode {
		args = append([]string{"--json"}, args...)
	}
	stdout, stderr, code, runErr := activeScenario.realCluster.RunTUI(args...)
	activeScenario.lastBody = []byte(stdout)
	activeScenario.lastStatus = code
	if runErr != nil && code == 0 {
		return fmt.Errorf("run standalone btw: %v; stderr=%s", runErr, stderr)
	}
	if code != 0 {
		return fmt.Errorf("standalone btw exit code=%d stderr=%s output=%s", code, stderr, stdout)
	}
	return nil
}

// standaloneOutput returns the recorded standalone output.
func standaloneOutput() string {
	return string(activeScenario.lastBody)
}

// assertStandaloneReceiptSection proves the standalone surface renders this
// service's own receipt instead of a JSON envelope.
func assertStandaloneReceiptSection() error {
	text := standaloneOutput()
	for _, value := range []string{"confirmed result", "delivery_boundary:", "effect_certainty:"} {
		if !strings.Contains(text, value) {
			return fmt.Errorf("standalone output is missing the service receipt field %q: %s", value, text)
		}
	}
	return nil
}

// assertStandaloneProviderSection proves the provider document is rendered under
// its own labelled section, separate from this service's receipt.
func assertStandaloneProviderSection() error {
	text := standaloneOutput()
	index := strings.Index(text, "provider_response:")
	if index < 0 {
		return fmt.Errorf("standalone output is missing the provider raw return section: %s", text)
	}
	if strings.TrimSpace(text[index+len("provider_response:"):]) == "" {
		return fmt.Errorf("standalone provider raw return section is empty: %s", text)
	}
	return nil
}

// assertStandaloneProviderDocumentVerbatim proves the document is not escaped
// inside a JSON string, which is the defect this scenario guards. The fixture
// provider answers every non-stop operation with its accepted document, so that
// document is the expected verbatim content.
func assertStandaloneProviderDocumentVerbatim() error {
	text := standaloneOutput()
	if !strings.Contains(text, `"outcome":"accepted"`) {
		return fmt.Errorf("standalone output does not carry the provider document verbatim: %s", text)
	}
	if strings.Contains(text, `\"`) {
		return fmt.Errorf("standalone output escaped the provider document: %s", text)
	}
	return nil
}

// assertStandaloneJSONDocument proves --json still emits one parseable document.
func assertStandaloneJSONDocument() error {
	var value any
	if err := json.Unmarshal(activeScenario.lastBody, &value); err != nil {
		return fmt.Errorf("standalone --json output is not one JSON document: %w in %s", err, activeScenario.lastBody)
	}
	return nil
}

// assertStandaloneJSONProviderDocument proves the envelope still carries the
// provider document, so a script loses no evidence.
func assertStandaloneJSONProviderDocument() error {
	var value map[string]any
	if err := json.Unmarshal(activeScenario.lastBody, &value); err != nil {
		return fmt.Errorf("decode standalone --json output: %w", err)
	}
	document, ok := value["provider_response"].(string)
	if !ok || document == "" {
		return fmt.Errorf("standalone --json output carries no provider document: %s", activeScenario.lastBody)
	}
	if !strings.Contains(document, `"outcome":"accepted"`) {
		return fmt.Errorf("standalone --json provider document is not the provider answer: %s", document)
	}
	return nil
}
