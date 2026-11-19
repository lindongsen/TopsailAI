package bdd

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/client"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	"topsailai_agent_cluster/tests/harness"
)

// registerEndpointQueryPermissionSteps registers the read and query permission
// scenarios.
//
// The family runs on the TopsailAI adapter because the generic fixture adapter
// implements only ReadOutput: it has no HistoryHandler, MessagesHandler,
// ModelCatalogHandler or ProjectHandler, so those four reads would be refused as
// unsupported before the policy hook and a scenario on that adapter would pass
// while proving nothing about authorization.
func registerEndpointQueryPermissionSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster whose endpoint policy separates view from read output$`, startQueryMatrixCluster)
	ctx.Step(`^the (model catalog|launch options|history|messages|metrics|detail|output snapshot|output follow) is read with the (view|read output) credential$`, performQueryRead)
	ctx.Step(`^the (model catalog|launch options|history|messages|metrics|detail|output snapshot|output follow) read is allowed and reaches the provider$`, assertQueryAllowed)
	ctx.Step(`^the (model catalog|launch options|history|messages|metrics|detail|output snapshot|output follow) read is refused with policy denied and exposes nothing$`, assertQueryRefused)
}

// queryModelCatalogOperation is the provider operation name the mock records for
// a catalog read. It is deliberately separate from the feature-file display name
// below: the display name is what a scenario says, while this is what the provider
// writes into its invocation record, and conflating the two made the count read
// zero while the provider had in fact been invoked.
const queryModelCatalogOperation = "model.catalog"

// querySessionMetricsOperation and querySessionDetailOperation are the provider
// query names the mock records for the two new reads. They are the wire names,
// not the feature-file display names, for the same reason as the catalog
// operation above: the display name is what a scenario says, while this is what
// the provider writes into its invocation record.
const (
	querySessionMetricsOperation = "session.metrics"
	querySessionDetailOperation  = "session.detail"
)

// The eight read operations under test, named as the feature file names them.
const (
	queryModelCatalog   = "model catalog"
	queryLaunchOptions  = "launch options"
	queryHistory        = "history"
	queryMessages       = "messages"
	queryMetrics        = "metrics"
	queryDetail         = "detail"
	queryOutputSnapshot = "output snapshot"
	queryOutputFollow   = "output follow"
)

// The two credentials the scenarios present. Both exist in the policy directory,
// so a refusal is caused by the missing operation and never by a credential the
// Endpoint does not know.
const (
	queryMatrixViewToken       = "bdd-query-view-token"
	queryMatrixReadOutputToken = "bdd-query-read-output-token"
)

// queryMatrixFollowChunkTarget is how many chunks a positive follow scenario
// waits for before it stops reading. The fixture writes one record every 150ms
// and then stays alive for 30 seconds, so waiting for the stream to end would
// make the scenario cost half a minute and prove nothing extra.
const queryMatrixFollowChunkTarget = 3

// queryMatrixFollowDeadline bounds how long a follow scenario reads. A refusal
// arrives immediately, so a refused follow that reaches this deadline has already
// failed the "no child process was started" assertion.
const queryMatrixFollowDeadline = 8 * time.Second

// queryMatrixRefusalBudget is the longest a refused follow may take. A started
// provider child would keep the stream open for the fixture's 30-second sleep, so
// a fast terminal record is the observable evidence that no child was spawned.
const queryMatrixRefusalBudget = 5 * time.Second

// queryReadOutcome is what one read produced, kept so the assertion steps can
// inspect it without repeating the call.
type queryReadOutcome struct {
	// operation is the read that was performed, so an assertion cannot pass
	// against a different read's result.
	operation string
	// credential names which token was presented.
	credential string
	// err is the transport or HTTP-level failure. A policy refusal of the five
	// request/response reads arrives here, because the Server maps it to 403.
	err error
	// errorCode is the Endpoint's own refusal or failure code. A refused follow
	// arrives here instead of in err, because the Server streams it inside a 200
	// response.
	errorCode string
	// payloadSize counts the provider-derived records the response carried.
	payloadSize int
	// content is provider-derived text, used to prove the read reached the
	// adapter rather than returning an empty success.
	content string
	// observedAtMS is the Endpoint's observation stamp. A non-zero value proves
	// the adapter answered, which is the only evidence available for the reads
	// the fixture does not record.
	observedAtMS int64
	// inbound and outbound are the two message counts, kept as separate fields
	// rather than one formatted string so an assertion can prove the two
	// positions were not swapped. A formatted "7/3" would pass even if the
	// adapter had written the counts in the wrong order.
	inbound int
	outbound int
	// providerMetadata is the provider session record the detail read returned.
	// It is kept verbatim so an assertion can prove the document was forwarded
	// rather than re-encoded from the fields the cluster models.
	providerMetadata string
	// providerRuntime is the reserved detail seam. It is expected to stay empty
	// until a source is chosen, so an assertion can prove the cluster reports it
	// as not reported instead of inventing one.
	providerRuntime string
	// chunks counts streamed records, for the follow read.
	chunks int
	// elapsed is how long the read took, used to prove a refused follow started
	// no child process.
	elapsed time.Duration
}

// queryMatrixResourceID and queryMatrixGeneration address the live fixture
// session. They are resolved from the committed inventory, because the cluster
// mints the opaque ID and the generation is provider evidence.
var (
	queryMatrixResourceID string
	queryMatrixGeneration string
)

// queryMatrixResult holds the most recent read.
var queryMatrixResult queryReadOutcome

// startQueryMatrixCluster starts one real cluster whose policy directory grants
// two disjoint scopes.
//
// The policy files are written before the Endpoint starts, because the harness
// captures the Endpoint environment at that moment. Appending afterwards would
// leave the running Endpoint permissive and every negative scenario would pass
// while proving nothing.
func startQueryMatrixCluster() error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	queryMatrixResult = queryReadOutcome{}
	policyDir, err := writeAccessPolicyGrants([]accessPolicyGrant{
		// The view scope covers the four read-only queries and nothing else.
		{Token: queryMatrixViewToken, Scopes: []string{security.ScopeView}},
		// The read output scope covers the two output reads and nothing else.
		{Token: queryMatrixReadOutputToken, Scopes: []string{security.ScopeReadOutput}},
	})
	if err != nil {
		return err
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		EndpointEnvironment: map[string]string{"AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR": policyDir},
	})
	if err != nil {
		return err
	}
	activeScenario.world.realCluster = cluster
	activeScenario.realCluster = cluster
	resourceID, generation, err := activeScenario.world.resolveRealTarget("fixture-session", "")
	if err != nil {
		return err
	}
	queryMatrixResourceID = resourceID
	queryMatrixGeneration = generation
	return nil
}

// performQueryRead performs one read with one credential and records the outcome.
//
// The read goes through the production API client, so the Endpoint token travels
// in the header the shipped CLI uses and the Server forwards it without
// interpreting it. Calling the Endpoint policy object directly would prove the
// policy works while proving nothing about the path an operator takes.
func performQueryRead(operation, credential string) error {
	if activeScenario == nil || activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	token := queryMatrixViewToken
	if credential == "read output" {
		token = queryMatrixReadOutputToken
	}
	api := client.NewAPIClient(activeScenario.realCluster.URL(""), "secret")
	// The harness Server runs in bearer mode, so this in-process client must
	// present the same scheme. An empty mode would fall back to the HMAC default
	// and be refused before the request reached the policy hook under test.
	api.AuthMode = security.ModeBearer
	api.EndpointTokens = map[string]string{scopedEndpointID: token}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	outcome := queryReadOutcome{operation: operation, credential: credential}
	started := time.Now()
	switch operation {
	case queryModelCatalog:
		result, err := api.GetModelCatalog(ctx, scopedEndpointID, protocol.ModelCatalogQuery{Target: protocol.CommandTarget{Kind: protocol.ResourceSession, ResourceID: queryMatrixResourceID, ProviderGeneration: queryMatrixGeneration}})
		outcome.err = err
		outcome.errorCode = result.ErrorCode
		outcome.payloadSize = len(result.Profiles)
		outcome.observedAtMS = result.ObservedAtMS
	case queryLaunchOptions:
		result, err := api.GetLaunchOptions(ctx, scopedEndpointID, "")
		outcome.err = err
		outcome.errorCode = result.ErrorCode
		outcome.payloadSize = len(result.Handlers)
	case queryHistory:
		result, err := api.GetHistory(ctx, scopedEndpointID, 0)
		outcome.err = err
		outcome.errorCode = result.ErrorCode
		outcome.payloadSize = len(result.Rows)
		outcome.observedAtMS = result.ObservedAtMS
	case queryMessages:
		result, err := api.GetMessages(ctx, scopedEndpointID, messagesFixtureSession, 0, 0)
		outcome.err = err
		outcome.errorCode = result.ErrorCode
		outcome.payloadSize = len(result.Messages)
		outcome.observedAtMS = result.ObservedAtMS
		outcome.content = result.ProviderSessionID
	case queryMetrics:
		// The target is the provider session key, not the cluster resource ID,
		// because a session with no live process has no cluster ID and metrics is
		// exactly the read an operator wants for such a session.
		result, err := api.GetMetrics(ctx, scopedEndpointID, messagesFixtureSession)
		outcome.err = err
		outcome.errorCode = result.ErrorCode
		outcome.observedAtMS = result.ObservedAtMS
		outcome.content = result.ProviderSessionID
		outcome.inbound = result.Messages.Inbound
		outcome.outbound = result.Messages.Outbound
	case queryDetail:
		result, err := api.GetDetail(ctx, scopedEndpointID, messagesFixtureSession)
		outcome.err = err
		outcome.errorCode = result.ErrorCode
		outcome.observedAtMS = result.ObservedAtMS
		outcome.content = result.ProviderSessionID
		outcome.providerMetadata = result.ProviderMetadata
		outcome.providerRuntime = result.ProviderRuntime
	case queryOutputSnapshot:
		result, err := api.GetOutput(ctx, scopedEndpointID, queryMatrixResourceID, queryMatrixGeneration, 0, 0)
		outcome.err = err
		outcome.errorCode = result.ErrorCode
		outcome.observedAtMS = result.ObservedAtMS
		outcome.content = result.Data
	case queryOutputFollow:
		if err := readQueryFollow(ctx, api, &outcome); err != nil {
			return err
		}
	default:
		return fmt.Errorf("unknown query operation %q", operation)
	}
	outcome.elapsed = time.Since(started)
	queryMatrixResult = outcome
	return nil
}

// readQueryFollow reads a bounded number of streamed records.
//
// A refusal is not an HTTP failure: the Server answers 200 and streams the
// Endpoint's terminal record, so the refusal code arrives in the end record
// rather than in the returned error. Both channels are captured, because an
// assertion that only inspected the error would never see a refused follow.
func readQueryFollow(ctx context.Context, api *client.APIClient, outcome *queryReadOutcome) error {
	chunks, err := api.FollowOutput(ctx, scopedEndpointID, queryMatrixResourceID, queryMatrixGeneration, 0, queryMatrixFollowChunkTarget)
	if err != nil {
		outcome.err = err
		return nil
	}
	deadline := time.After(queryMatrixFollowDeadline)
	for {
		select {
		case chunk, ok := <-chunks:
			if !ok {
				return nil
			}
			if chunk.End {
				outcome.errorCode = chunk.ErrorCode
				return nil
			}
			outcome.chunks++
			outcome.content += strings.Join(chunk.Lines, "\n")
			if outcome.chunks >= queryMatrixFollowChunkTarget {
				return nil
			}
		case <-deadline:
			return nil
		}
	}
}

// assertQueryAllowed proves the matching credential was permitted and the read
// reached the adapter.
//
// The assertion names the operation, so a scenario cannot pass against a
// different read's result. It rejects an empty success as well as an error code,
// because a read that returns nothing looks identical to a read that was refused
// if only the error is checked.
func assertQueryAllowed(operation string) error {
	outcome := queryMatrixResult
	if outcome.operation != operation {
		return fmt.Errorf("the last read was %q, not %q", outcome.operation, operation)
	}
	if outcome.err != nil {
		return fmt.Errorf("allowed %s read failed: %w", operation, outcome.err)
	}
	if outcome.errorCode != "" {
		return fmt.Errorf("allowed %s read ended with error_code=%q", operation, outcome.errorCode)
	}
	switch operation {
	case queryModelCatalog:
		if outcome.payloadSize == 0 {
			return fmt.Errorf("allowed model catalog read returned no profiles")
		}
		if outcome.observedAtMS == 0 {
			return fmt.Errorf("allowed model catalog read carried no observation time, so the adapter did not answer")
		}
		count, err := queryMatrixInvocations(queryModelCatalogOperation)
		if err != nil {
			return err
		}
		if count != 1 {
			return fmt.Errorf("the provider received %d model catalog invocations, want exactly one", count)
		}
	case queryLaunchOptions:
		if outcome.payloadSize == 0 {
			return fmt.Errorf("allowed launch options read returned no handlers")
		}
	case queryHistory:
		// The fixture answers an empty history, so the row count cannot prove the
		// adapter ran. The observation stamp can: only the adapter stamps it.
		if outcome.observedAtMS == 0 {
			return fmt.Errorf("allowed history read carried no observation time, so the adapter did not answer")
		}
	case queryMessages:
		if outcome.content != messagesFixtureSession {
			return fmt.Errorf("allowed messages read answered for %q, want the requested session", outcome.content)
		}
		if outcome.observedAtMS == 0 {
			return fmt.Errorf("allowed messages read carried no observation time, so the adapter did not answer")
		}
	case queryMetrics:
		if outcome.content != messagesFixtureSession {
			return fmt.Errorf("allowed metrics read answered for %q, want the requested session", outcome.content)
		}
		if outcome.observedAtMS == 0 {
			return fmt.Errorf("allowed metrics read carried no observation time, so the adapter did not answer")
		}
		// The fixture reports inbound=7 and outbound=3 on purpose. Equal counts
		// would let a swapped mapping pass, so the two positions are asserted
		// separately and against different values.
		if outcome.inbound != 7 || outcome.outbound != 3 {
			return fmt.Errorf("allowed metrics read reported inbound=%d outbound=%d, want inbound=7 outbound=3", outcome.inbound, outcome.outbound)
		}
		count, err := queryMatrixInvocations(querySessionMetricsOperation)
		if err != nil {
			return err
		}
		if count != 1 {
			return fmt.Errorf("the provider received %d session metrics invocations, want exactly one", count)
		}
	case queryDetail:
		if outcome.content != messagesFixtureSession {
			return fmt.Errorf("allowed detail read answered for %q, want the requested session", outcome.content)
		}
		if outcome.observedAtMS == 0 {
			return fmt.Errorf("allowed detail read carried no observation time, so the adapter did not answer")
		}
		// The fixture provider_metadata carries a field the cluster does not model.
		// Its presence is the only evidence that the document was forwarded
		// verbatim rather than re-encoded from the fields the cluster knows,
		// because a re-encoded document would still contain every field the
		// cluster models.
		if !strings.Contains(outcome.providerMetadata, "unmodelled_field") {
			return fmt.Errorf("allowed detail read returned provider_metadata %q, want the provider record verbatim", outcome.providerMetadata)
		}
		// provider_runtime is a seam with no source yet. An empty value is the
		// correct answer, and a non-empty one would mean the cluster invented a
		// runtime observation nobody decided on.
		if outcome.providerRuntime != "" {
			return fmt.Errorf("allowed detail read reported provider_runtime %q, want the seam left empty", outcome.providerRuntime)
		}
		count, err := queryMatrixInvocations(querySessionDetailOperation)
		if err != nil {
			return err
		}
		if count != 1 {
			return fmt.Errorf("the provider received %d session detail invocations, want exactly one", count)
		}
	case queryOutputSnapshot:
		// The marker is the one the harness provider actually emits. The previous
		// literal "fixture output for" came from a fixture that has since been
		// deleted (it was never built by any target), so the assertion could not
		// pass regardless of what the Cluster did. Four other assertions depend on
		// this same marker, so the marker is the contract and the stale literal was
		// the defect.
		if !strings.Contains(outcome.content, "provider output marker") {
			return fmt.Errorf("allowed output snapshot read returned %q, want the provider output", outcome.content)
		}
	case queryOutputFollow:
		if outcome.chunks == 0 {
			return fmt.Errorf("allowed output follow read delivered no chunk")
		}
		if !strings.Contains(outcome.content, "fixture follow") {
			return fmt.Errorf("allowed output follow read delivered %q, want the provider records", outcome.content)
		}
	}
	return nil
}

// assertQueryRefused proves the unrelated credential was refused with
// policy_denied and that the refusal exposed nothing.
//
// The code is named rather than accepting any failure, because every other way a
// read can fail also produces no payload: an adapter that cannot answer reports
// unsupported, an offline Endpoint reports endpoint_unavailable, and a provider
// failure reports provider_error. Only the code distinguishes a policy decision
// from those accidents.
func assertQueryRefused(operation string) error {
	outcome := queryMatrixResult
	if outcome.operation != operation {
		return fmt.Errorf("the last read was %q, not %q", outcome.operation, operation)
	}
	refused := outcome.errorCode == protocol.PolicyDenied ||
		(outcome.err != nil && strings.Contains(outcome.err.Error(), protocol.PolicyDenied))
	if !refused {
		return fmt.Errorf("refused %s read reported error=%v error_code=%q, want %s", operation, outcome.err, outcome.errorCode, protocol.PolicyDenied)
	}
	if outcome.payloadSize != 0 {
		return fmt.Errorf("refused %s read still carried %d records", operation, outcome.payloadSize)
	}
	if outcome.content != "" {
		return fmt.Errorf("refused %s read still carried provider content %q", operation, outcome.content)
	}
	if outcome.chunks != 0 {
		return fmt.Errorf("refused %s read still delivered %d chunks", operation, outcome.chunks)
	}
	if outcome.observedAtMS != 0 {
		return fmt.Errorf("refused %s read still carried an observation time, so the adapter was consulted", operation)
	}
	if operation == queryOutputFollow && outcome.elapsed > queryMatrixRefusalBudget {
		return fmt.Errorf("refused output follow took %s, which means a provider child was started", outcome.elapsed)
	}
	return nil
}

// queryMatrixInvocations counts the recorded provider invocations whose first
// argv token is command.
//
// The fixture records only the argv, so the command name is the only way to tell
// a model catalog read from a control action. Counting every record would let an
// unrelated invocation satisfy the assertion.
func queryMatrixInvocations(operation string) (int, error) {
	if activeScenario.realCluster == nil {
		return 0, fmt.Errorf("real cluster is not running")
	}
	records, err := activeScenario.realCluster.ProviderInvocationsE()
	if err != nil {
		return 0, err
	}
	count := 0
	for _, record := range records {
		if recorded, _ := record["operation"].(string); recorded == operation {
			count++
		}
	}
	return count, nil
}
