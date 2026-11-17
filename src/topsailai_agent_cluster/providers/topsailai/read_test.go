package main

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"strconv"
	"strings"
	"testing"
	"time"
)

type runnerAnswer struct {
	stdout string
	stderr string
	err    error
}
type recordedCall struct{ args []string }
type scriptedRunner struct {
	t       *testing.T
	answers map[string][]runnerAnswer
	calls   []recordedCall
}

func (r *scriptedRunner) Run(_ context.Context, args []string, _ []byte) ([]byte, []byte, error) {
	key := strings.Join(args, "\x00")
	r.calls = append(r.calls, recordedCall{append([]string(nil), args...)})
	values := r.answers[key]
	if len(values) == 0 {
		r.t.Fatalf("unexpected CLI call: %v", args)
	}
	answer := values[0]
	r.answers[key] = values[1:]
	return []byte(answer.stdout), []byte(answer.stderr), answer.err
}

// supportedPlatform is a host that can stop a provider process. It is the value
// the startup probe reports on a Linux host with a readable process table and a
// working pidfd, so a test that exercises agent.stop states the host it assumes
// instead of inheriting whatever the test machine happens to be.
var supportedPlatform = platformCapabilities{ProcAvailable: true, PidfdAvailable: true}

// unsupportedPlatform is a host that cannot stop a provider process.
var unsupportedPlatform = platformCapabilities{}

func fixedProvider(r commandRunner) *provider {
	return &provider{runner: r, now: func() time.Time { return time.UnixMilli(1700000000123) }, platform: supportedPlatform}
}
func answer(document string) []runnerAnswer { return []runnerAnswer{{stdout: document}} }
func queryRequest(name string, target *target, payload string) request {
	value := validRequest(functionQuery)
	value.Query = &namedContract{Name: name, Version: "v1"}
	value.Target = target
	value.Payload = json.RawMessage(payload)
	return value
}
func sessionTarget(t *testing.T) *target {
	t.Helper()
	key, err := providerSessionKey(workspaceItem{SessionID: "s-1", ProviderRowKey: "row", PID: 42})
	if err != nil {
		t.Fatal(err)
	}
	return &target{ResourceKind: resourceSession, ProviderResourceKey: key}
}

func TestDiscoverEmitsStableProviderObservationWithoutClusterID(t *testing.T) {
	doc := `{"items":[{"session_id":"s-1","filename":"row","pid":42,"process_generation":7,"state":"input","session_name":"demo","project_workspace":"/work"}],"total":1}`
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{"workspace\x00list\x00--json\x00--local": answer(doc)}}
	p := fixedProvider(r)
	response := p.dispatch(context.Background(), validRequest(functionDiscover))
	if !response.OK || response.Discovery == nil || len(response.Discovery.Observations) != 1 {
		t.Fatalf("response=%+v", response)
	}
	got := response.Discovery.Observations[0]
	if got.ProviderGeneration != "7" || got.State != "waiting_input" || got.ResourceKind != resourceSession {
		t.Fatalf("observation=%+v", got)
	}
	if strings.Contains(string(got.Attributes), "cluster_") {
		t.Fatalf("cluster field leaked: %s", got.Attributes)
	}
	var attrs sessionAttributes
	if err := json.Unmarshal(got.Attributes, &attrs); err != nil || attrs.ProviderSessionID != "s-1" || attrs.ProviderPID != 42 {
		t.Fatalf("attributes=%+v err=%v", attrs, err)
	}
	key2, err := providerSessionKey(workspaceItem{SessionID: "s-1", ProviderRowKey: "row", PID: 9001})
	if err != nil || key2 != got.ProviderResourceKey {
		t.Fatalf("stable key=%q err=%v", key2, err)
	}
}

// TestDiscoverEmitsBothDirectoryCandidates proves the provider forwards the two
// directories the Cluster needs to resolve an operator command.
//
// project_workspace is the stable location and pwd is the directory the session was
// started from. Emitting only the first one removed the fallback the Cluster used to
// have, so a session whose project lives on another host became unrunnable. The
// assertion names both fields, because a provider that emitted only one would still
// satisfy a "the attributes are present" check.
func TestDiscoverEmitsBothDirectoryCandidates(t *testing.T) {
	doc := `{"items":[{"session_id":"s-1","filename":"row","pid":42,"process_generation":7,"project_workspace":"/work/project","pwd":"/work/project/sub"}],"total":1}`
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{"workspace\x00list\x00--json\x00--local": answer(doc)}}
	response := fixedProvider(r).dispatch(context.Background(), validRequest(functionDiscover))
	if !response.OK || response.Discovery == nil || len(response.Discovery.Observations) != 1 {
		t.Fatalf("response=%+v", response)
	}
	var attrs sessionAttributes
	if err := json.Unmarshal(response.Discovery.Observations[0].Attributes, &attrs); err != nil {
		t.Fatalf("decode attributes: %v", err)
	}
	if attrs.ProviderProjectWorkspace != "/work/project" {
		t.Fatalf("project workspace = %q", attrs.ProviderProjectWorkspace)
	}
	if attrs.ProviderPwd != "/work/project/sub" {
		t.Fatalf("pwd = %q", attrs.ProviderPwd)
	}
}

// TestLaunchOptionsRejectsAnUnsafeProjectPath proves the Provider applies the same
// folder rule the Cluster applies.
//
// The Cluster refuses a folder with leading or trailing whitespace and a folder
// containing a control character. Checking only for emptiness let both through, so
// the Provider reported a project the Cluster would never accept. Each rejected
// shape is asserted separately, because a single "it failed" check cannot tell which
// rule fired.
func TestLaunchOptionsRejectsAnUnsafeProjectPath(t *testing.T) {
	cases := map[string]string{
		"leading whitespace":  `[{"name":"demo","path":" /work/demo"}]`,
		"trailing whitespace": `[{"name":"demo","path":"/work/demo "}]`,
		"control character":   `[{"name":"demo","path":"/work/de\u0007mo"}]`,
	}
	for name, document := range cases {
		t.Run(name, func(t *testing.T) {
			r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{"project\x00list\x00--json": answer(document)}}
			response := fixedProvider(r).dispatch(context.Background(), queryRequest(queryLaunchOptions, nil, `{"include_projects":true}`))
			if response.OK || response.Error == nil {
				t.Fatalf("an unsafe project path was accepted: %+v", response)
			}
		})
	}
}

// TestLaunchOptionsAcceptsAnOrdinaryProjectPath proves the rule is not a blanket
// refusal.
//
// Without this half, a validator that rejected every path would pass the rejection
// test while making every project unlaunchable.
func TestLaunchOptionsAcceptsAnOrdinaryProjectPath(t *testing.T) {
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{"project\x00list\x00--json": answer(`[{"name":"demo","path":"/work/demo"}]`)}}
	response := fixedProvider(r).dispatch(context.Background(), queryRequest(queryLaunchOptions, nil, `{"include_projects":true}`))
	if !response.OK || response.QueryResult == nil {
		t.Fatalf("response=%+v", response)
	}
	if !strings.Contains(string(response.QueryResult), "/work/demo") {
		t.Fatalf("query result = %s", response.QueryResult)
	}
}

func TestInspectMatchesExactProviderRow(t *testing.T) {
	target := sessionTarget(t)
	doc := `{"items":[{"session_id":"s-1","filename":"other","pid":42,"process_generation":8},{"session_id":"s-1","filename":"row","pid":99,"process_generation":9}],"total":2}`
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{"workspace\x00list\x00--json": answer(doc)}}
	p := fixedProvider(r)
	request := validRequest(functionInspect)
	request.Target = target
	response := p.dispatch(context.Background(), request)
	if !response.OK || response.Inspection == nil || !response.Inspection.Found || !response.Inspection.Live {
		t.Fatalf("response=%+v", response)
	}
	if response.Inspection.Observation.ProviderGeneration != "9" {
		t.Fatalf("inspection=%+v", response.Inspection)
	}
}

func TestTypedQueriesReturnProviderFactsWithoutClusterIDs(t *testing.T) {
	session := sessionTarget(t)
	tests := []struct {
		name, query, payload string
		target               *target
		answers              map[string][]runnerAnswer
		forbidden            string
	}{
		{name: "launch", query: queryLaunchOptions, payload: `{"include_projects":true}`, answers: map[string][]runnerAnswer{"project\x00list\x00--json": answer(`[{"name":"demo","path":"/work/demo"}]`)}, forbidden: "launch_profile_id"},
		{name: "history", query: queryHistoryMessages, payload: `{"limit":10}`, answers: map[string][]runnerAnswer{"project\x00list_sessions\x00--json": answer(`[{"session_id":"s-old","status":"Idle","task":"work"}]`)}, forbidden: "resource_id"},
		{name: "models", query: queryModelCatalog, payload: `{}`, target: session, answers: map[string][]runnerAnswer{"workspace\x00list\x00--json\x00--local": answer(`{"items":[{"session_id":"s-1","filename":"row","pid":77}]}`), "models\x00list\x00--json": answer(`[{"name":"fast","protocol":"openai-compatible"}]`), "runtime\x00control\x00call_instruction\x00-s\x00s-1\x00-a\x00{\"args\":null,\"instruction\":\"agent.llm\"}\x00--json": answer(`{"ok":true,"response":{"status":"ok","result":"fast"}}`)}, forbidden: "model_profile_id"},
		{name: "messages", query: querySessionMessages, payload: `{"max_chars":0,"max_tokens":0}`, target: &target{ResourceKind: resourceSession, ProviderResourceKey: "s-1"}, answers: map[string][]runnerAnswer{"session\x00info\x00s-1\x00--json": answer(`{}`), "session\x00history\x00s-1\x00--json": answer(`{"ok":true,"session_id":"s-1","message_count":1,"messages":[{"role":"user","content":"hello world","create_time":"2026-01-01T00:00:00Z"}]}`)}, forbidden: "cluster_session_id"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			r := &scriptedRunner{t: t, answers: test.answers}
			p := fixedProvider(r)
			response := p.dispatch(context.Background(), queryRequest(test.query, test.target, test.payload))
			if !response.OK || len(response.QueryResult) == 0 {
				t.Fatalf("response=%+v", response)
			}
			if strings.Contains(string(response.QueryResult), test.forbidden) {
				t.Fatalf("forbidden field in %s", response.QueryResult)
			}
			if strings.Contains(string(response.QueryResult), `"provider_resource_key":""`) {
				t.Fatalf("empty provider key in %s", response.QueryResult)
			}
		})
	}
}

// TestHistoryRowConvertsProviderCreateTime proves the history row reads the
// provider's own creation timestamp field.
//
// The provider emits `create_time` on every `project list_sessions --json` row.
// An earlier version of this Provider read a duplicate field named
// `create_time_raw`, which the provider has since removed. Because
// providerTimeMS returns 0 for an absent field and the result field carries
// `omitempty`, a stale field name silently zeroed `created_at_ms` with no error
// and no log line. This test pins the field name, so a future rename fails here
// instead of disappearing from the JSON output.
func TestHistoryRowConvertsProviderCreateTime(t *testing.T) {
	document := `[{"session_id":"s-old","status":"Idle","task":"work","create_time":"2026-11-15T09:12:23","modified_time_raw":"2026-11-15T09:18:37","no":1}]`
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{"project\x00list_sessions\x00--json": answer(document)}}
	response := fixedProvider(r).dispatch(context.Background(), queryRequest(queryHistoryMessages, nil, `{"limit":10}`))
	if !response.OK || len(response.QueryResult) == 0 {
		t.Fatalf("response=%+v", response)
	}
	var result historyResult
	if err := json.Unmarshal(response.QueryResult, &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Rows) != 1 {
		t.Fatalf("rows=%+v", result.Rows)
	}
	expected := time.Date(2026, 11, 15, 9, 12, 23, 0, time.Local).UnixMilli()
	if result.Rows[0].CreatedAtMS != expected {
		t.Fatalf("created_at_ms=%d, want %d", result.Rows[0].CreatedAtMS, expected)
	}
	if result.Rows[0].ModifiedAtMS == 0 {
		t.Fatalf("modified_at_ms was not converted: %+v", result.Rows[0])
	}
}

func TestReadOutputPreservesAndAppliesBounds(t *testing.T) {
	session := sessionTarget(t)
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"workspace\x00list\x00--json\x00--local":                         answer(`{"items":[{"session_id":"s-1","filename":"row","pid":77}]}`),
		"runtime\x00logs\x00-s\x00s-1\x00-p\x0077\x00-n\x0020\x00--json": answer(`{"ok":true,"response":{"lines":["abcdef"],"truncated":false,"scan_limited":false}}`),
	}}
	p := fixedProvider(r)
	request := validRequest(functionReadOutput)
	request.Target = session
	request.Payload = json.RawMessage(`{"max_bytes":4,"max_lines":0}`)
	response := p.dispatch(context.Background(), request)
	if !response.OK || response.Output == nil {
		t.Fatalf("response=%+v", response)
	}
	if response.Output.Content != "abcd" || !response.Output.Truncated || response.Output.Complete {
		t.Fatalf("output=%+v", response.Output)
	}
}

func TestReadFunctionsFailClosedOnInvalidPayloadAndProviderFailure(t *testing.T) {
	p := fixedProvider(&scriptedRunner{t: t, answers: map[string][]runnerAnswer{}})
	response := p.dispatch(context.Background(), queryRequest(queryLaunchOptions, nil, `{"include_projects":false,"cluster_id":"bad"}`))
	if response.OK || response.Error == nil || response.Error.Code != "invalid_request" {
		t.Fatalf("response=%+v", response)
	}
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{"workspace\x00list\x00--json\x00--local": {{stderr: "broken", err: errors.New("exit 1")}}}}
	response = fixedProvider(r).dispatch(context.Background(), validRequest(functionDiscover))
	if response.OK || response.Error == nil || !strings.Contains(response.Error.Message, "broken") {
		t.Fatalf("response=%+v", response)
	}
}

func TestProviderSessionKeyIsStableAcrossPIDChangesAndDistinctForSiblingRows(t *testing.T) {
	first, err := providerSessionKey(workspaceItem{SessionID: "shared", ProviderRowKey: "manager.stdout", PID: 10})
	if err != nil {
		t.Fatal(err)
	}
	restarted, err := providerSessionKey(workspaceItem{SessionID: "shared", ProviderRowKey: "manager.stdout", PID: 999})
	if err != nil {
		t.Fatal(err)
	}
	sibling, err := providerSessionKey(workspaceItem{SessionID: "shared", ProviderRowKey: "task.stdout", PID: 10, IsTask: true})
	if err != nil {
		t.Fatal(err)
	}
	if first != restarted {
		t.Fatalf("key changed across PID restart: %q != %q", first, restarted)
	}
	if first == sibling {
		t.Fatalf("sibling rows share key %q", first)
	}
	if len(first) > maxProviderKeyLength {
		t.Fatalf("key length=%d", len(first))
	}
}

func TestReadContractsRejectMissingAndDuplicateProviderKeys(t *testing.T) {
	tests := []struct {
		name, function, document string
		request                  request
		call                     string
	}{
		{name: "discover missing filename", function: functionDiscover, document: `{"items":[{"session_id":"s"}]}`, request: validRequest(functionDiscover), call: "workspace\x00list\x00--json\x00--local"},
		{name: "discover duplicate row", function: functionDiscover, document: `{"items":[{"session_id":"s","filename":"row"},{"session_id":"s","filename":"row"}]}`, request: validRequest(functionDiscover), call: "workspace\x00list\x00--json\x00--local"},
		{name: "history missing session", function: functionQuery, document: `[{"status":"Idle"}]`, request: queryRequest(queryHistoryMessages, nil, `{"limit":0}`), call: "project\x00list_sessions\x00--json"},
		{name: "history duplicate session", function: functionQuery, document: `[{"session_id":"s"},{"session_id":"s"}]`, request: queryRequest(queryHistoryMessages, nil, `{"limit":0}`), call: "project\x00list_sessions\x00--json"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{test.call: answer(test.document)}}
			got := fixedProvider(r).dispatch(context.Background(), test.request)
			if got.OK || got.Error == nil {
				t.Fatalf("response=%+v", got)
			}
		})
	}
}

func TestBusinessCLIJSONRejectsExtraDocument(t *testing.T) {
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{"workspace\x00list\x00--json\x00--local": answer(`{"items":[]} {}`)}}
	got := fixedProvider(r).dispatch(context.Background(), validRequest(functionDiscover))
	if got.OK || got.Error == nil || !strings.Contains(got.Error.Message, "extra JSON document") {
		t.Fatalf("response=%+v", got)
	}
}

func TestTypedQueriesRejectWrongVersionKindAndUnknownField(t *testing.T) {
	wrongVersion := queryRequest(queryLaunchOptions, nil, `{"include_projects":false}`)
	wrongVersion.Query.Version = "v2"
	wrongKind := queryRequest(queryModelCatalog, &target{ResourceKind: resourceModelProfile, ProviderResourceKey: "x"}, `{}`)
	unknown := queryRequest(queryHistoryMessages, nil, `{"limit":0,"extra":true}`)
	for name, request := range map[string]request{"version": wrongVersion, "kind": wrongKind, "unknown": unknown} {
		t.Run(name, func(t *testing.T) {
			got := fixedProvider(&scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}).dispatch(context.Background(), request)
			if got.OK || got.Error == nil || got.Error.Code != "invalid_request" {
				t.Fatalf("response=%+v", got)
			}
		})
	}
}

func TestRuntimeLogArgsPreserveExactProviderSelectors(t *testing.T) {
	got := runtimeLogArgs(providerSessionTarget{SessionID: "s", PID: 4, IsTask: true}, 7, false)
	want := []string{"runtime", "logs", "-s", "s", "-p", "4", "--is-task", "-n", "7", "--json"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("args=%v", got)
	}
}

// TestReadOutputRejectsOutOfContractBounds proves the Provider fails closed even
// when a caller bypasses the Endpoint clamps.
func TestReadOutputRejectsOutOfContractBounds(t *testing.T) {
	for name, payload := range map[string]string{
		"bytes": `{"max_bytes":1048577,"max_lines":20}`,
		"lines": `{"max_bytes":4096,"max_lines":10001}`,
	} {
		t.Run(name, func(t *testing.T) {
			request := validRequest(functionReadOutput)
			request.Target = sessionTarget(t)
			request.Payload = json.RawMessage(payload)
			got := fixedProvider(&scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}).dispatch(context.Background(), request)
			if got.OK || got.Error == nil || got.Error.Code != "invalid_request" {
				t.Fatalf("response=%+v", got)
			}
		})
	}
}

// TestReadResultsEncodeEmptyCollectionsAsArrays pins the typed query and
// discovery contracts: an empty successful result is [] rather than null.
func TestReadResultsEncodeEmptyCollectionsAsArrays(t *testing.T) {
	tests := []struct {
		name     string
		request  request
		answers  map[string][]runnerAnswer
		required string
	}{
		{name: "discovery", request: validRequest(functionDiscover), answers: map[string][]runnerAnswer{"workspace\x00list\x00--json\x00--local": answer(`{"items":[],"total":0}`)}, required: `"observations":[]`},
		{name: "launch", request: queryRequest(queryLaunchOptions, nil, `{"include_projects":true}`), answers: map[string][]runnerAnswer{"project\x00list\x00--json": answer(`[]`)}, required: `"projects":[]`},
		{name: "history", request: queryRequest(queryHistoryMessages, nil, `{"limit":0}`), answers: map[string][]runnerAnswer{"project\x00list_sessions\x00--json": answer(`[]`)}, required: `"rows":[]`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got := fixedProvider(&scriptedRunner{t: t, answers: test.answers}).dispatch(context.Background(), test.request)
			if !got.OK {
				t.Fatalf("response=%+v", got)
			}
			document, err := json.Marshal(got)
			if err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(string(document), test.required) {
				t.Fatalf("document=%s, missing %s", document, test.required)
			}
		})
	}
}

// TestMessageHelpersPreserveProviderPresentationSemantics proves the standalone
// Provider keeps the old adapter's stored-body counts and step-record rendering.
//
// The body is asserted as the text it holds, not as a JSON string. The provider
// stores `raw_text` as a JSON string, so marshalling it would print a quoted body
// with every real newline escaped as \n, which collapses a multi-line answer onto
// one line. That was the reported defect, so this assertion states the readable
// form and would fail if the quoting came back.
func TestMessageHelpersPreserveProviderPresentationSemantics(t *testing.T) {
	stored := `{"raw_text":"hello","step_name":"task"}`
	if got := unwrapContent(stored); got != "topsailai.task\nhello" {
		t.Fatalf("unwrapped=%q", got)
	}
	if got := tokenCount("hello world"); got <= 0 {
		t.Fatalf("token count=%d", got)
	}
}

// TestUnwrapContentKeepsStepBodyLineStructure proves a multi-line step body keeps
// its real line breaks.
//
// The fixture carries three real newlines, because a single-line fixture cannot
// express the failure mode: a quoted dump of one line is still one line, so the
// assertion would pass while the defect was present. The escaped form is also
// rejected explicitly, so a body that is quoted again fails with a message naming
// the cause instead of only reporting a mismatch.
func TestUnwrapContentKeepsStepBodyLineStructure(t *testing.T) {
	stored := `{"raw_text":"first line\nsecond line\n\nfourth line","step_name":"final_answer"}`
	got := unwrapContent(stored)
	want := "topsailai.final_answer\nfirst line\nsecond line\n\nfourth line"
	if got != want {
		t.Fatalf("unwrapped=%q, want %q", got, want)
	}
	if strings.Contains(got, `\n`) {
		t.Fatalf("unwrapped body still carries an escaped newline: %q", got)
	}
	if strings.HasPrefix(got, "topsailai.final_answer\n\"") {
		t.Fatalf("unwrapped body is still a quoted JSON string: %q", got)
	}
}

// TestUnwrapContentKeepsNonStringStepBody proves a step body that is not a string
// keeps a faithful representation.
//
// Only a string has a plain-text form to prefer, so a structured body must keep
// the JSON form rather than being flattened by fmt.Sprint, which would print a map
// in Go syntax and lose the field names a reader needs.
func TestUnwrapContentKeepsNonStringStepBody(t *testing.T) {
	stored := `{"raw_text":{"kind":"note","count":2},"step_name":"observation"}`
	got := unwrapContent(stored)
	want := `topsailai.observation` + "\n" + `{"count":2,"kind":"note"}`
	if got != want {
		t.Fatalf("unwrapped=%q, want %q", got, want)
	}
}

// TestUnwrapContentKeepsExtraStepFields proves a record with fields beyond the step
// name and body still shows them.
//
// The extra fields are dumped as JSON, so this also proves the string body change
// did not disturb the remaining record.
func TestUnwrapContentKeepsExtraStepFields(t *testing.T) {
	stored := `{"raw_text":"body text","step_name":"task","tool":"read_file"}`
	got := unwrapContent(stored)
	want := "topsailai.task\nbody text\n" + `{"tool":"read_file"}`
	if got != want {
		t.Fatalf("unwrapped=%q, want %q", got, want)
	}
}

// TestProviderDocumentsContainNoClusterIdentityField checks all prohibited
// Cluster identity spellings rather than one query-specific example.
func TestProviderDocumentsContainNoClusterIdentityField(t *testing.T) {
	forbidden := []string{"launch_profile_id", "resource_id", "model_profile_id", "cluster_session_id", "command_id"}
	document := `{"items":[{"session_id":"s-1","filename":"row","pid":42,"process_generation":7}],"total":1}`
	got := fixedProvider(&scriptedRunner{t: t, answers: map[string][]runnerAnswer{"workspace\x00list\x00--json\x00--local": answer(document)}}).dispatch(context.Background(), validRequest(functionDiscover))
	encoded, err := json.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	for _, field := range forbidden {
		if strings.Contains(string(encoded), `"`+field+`"`) {
			t.Fatalf("forbidden field %q in %s", field, encoded)
		}
	}
}

// TestReadPayloadsRejectNull pins the Unit 1Q rule that null is never an
// alternative spelling for a typed request object.
func TestReadPayloadsRejectNull(t *testing.T) {
	tests := []request{
		queryRequest(queryLaunchOptions, nil, `null`),
		queryRequest(queryHistoryMessages, nil, `null`),
		queryRequest(queryModelCatalog, sessionTarget(t), `null`),
		queryRequest(querySessionMessages, &target{ResourceKind: resourceSession, ProviderResourceKey: "s-1"}, `null`),
	}
	output := validRequest(functionReadOutput)
	output.Target = sessionTarget(t)
	output.Payload = json.RawMessage(`null`)
	tests = append(tests, output)
	for _, request := range tests {
		t.Run(request.Function+request.QueryName(), func(t *testing.T) {
			got := fixedProvider(&scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}).dispatch(context.Background(), request)
			if got.OK || got.Error == nil || got.Error.Code != "invalid_request" {
				t.Fatalf("response=%+v", got)
			}
		})
	}
}

func (r request) QueryName() string {
	if r.Query == nil {
		return ""
	}
	return r.Query.Name
}

// TestSessionMetricsReadsRuntimeDocument proves the counts come from the runtime
// record the provider already collects, not from a per-row control call.
//
// The scripted runner fails on any unexpected argv, so this test also pins the
// spelling: an implementation that still asked for `agent.tokens` would not match
// the recorded key and would fail here instead of at runtime. The session selector
// is part of the pinned argv because collection runs after that filter, and a
// missing selector would make one row's read probe every row.
func TestSessionMetricsReadsRuntimeDocument(t *testing.T) {
	document := `{"items":[{"session_id":"s-1","filename":"s-1.42.session.stdout","is_task":false,` +
		`"runtime":{"state":"ok","error_code":"","pid":42,"data":{"ok":true,` +
		`"agent2llm":{"messages":68},"user2agent":{"messages":2}}}}],"total":1}`
	key := "workspace\x00list\x00--json\x00--local\x00-s\x00s-1\x00--include-runtime"
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{key: answer(document)}}
	response := fixedProvider(r).dispatch(context.Background(), queryRequest(
		querySessionMetrics, &target{ResourceKind: resourceSession, ProviderResourceKey: "s-1"}, `{}`))
	if !response.OK || len(response.QueryResult) == 0 {
		t.Fatalf("response=%+v", response)
	}
	var result metricsResult
	if err := json.Unmarshal(response.QueryResult, &result); err != nil {
		t.Fatal(err)
	}
	// The human listed user2agent first, so inbound is the operator side and
	// outbound is the model side. The provider's own text output prints
	// Agent2LLM first, which must not decide the Cluster's order.
	if result.Messages.Inbound != 2 || result.Messages.Outbound != 68 {
		t.Fatalf("messages=%+v, want inbound=2 outbound=68", result.Messages)
	}
	if result.ProviderSessionID != "s-1" {
		t.Fatalf("provider_session_id=%q", result.ProviderSessionID)
	}
}

// TestSessionMetricsMapsUnknownSessionToNotFound proves a session the provider
// does not list is reported as a missing session rather than as a provider fault.
//
// The provider answers an unknown selector with an empty document rather than an
// error, so absence from the document is the only evidence available. It must map
// onto the registry's own code so a caller sees one answer for one condition.
func TestSessionMetricsMapsUnknownSessionToNotFound(t *testing.T) {
	key := "workspace\x00list\x00--json\x00--local\x00-s\x00s-1\x00--include-runtime"
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		key: answer(`{"items":[],"total":0}`)}}
	response := fixedProvider(r).dispatch(context.Background(), queryRequest(
		querySessionMetrics, &target{ResourceKind: resourceSession, ProviderResourceKey: "s-1"}, `{}`))
	if response.OK || response.Error == nil {
		t.Fatalf("response=%+v", response)
	}
	if response.Error.Code != providerSessionNotFoundCode {
		t.Fatalf("code=%q, want %q", response.Error.Code, providerSessionNotFoundCode)
	}
}

// TestSessionMetricsRejectsUnmeasuredRuntime proves a row whose process did not
// answer is a provider failure, never a zero count.
//
// A rejected or unavailable runtime record carries no data, and reporting it as
// zero would claim the session holds no messages. That is a different statement
// from "nobody measured this session", and only the second one is true here.
func TestSessionMetricsRejectsUnmeasuredRuntime(t *testing.T) {
	cases := map[string]string{
		"rejected":    `{"state":"rejected","error_code":"control_rejected","pid":42,"data":null}`,
		"unavailable": `{"state":"unavailable","error_code":"endpoint_missing","pid":42,"data":null}`,
		"absent":      `null`,
		"no agent":    `{"state":"ok","error_code":"","pid":42,"data":{"ok":false}}`,
	}
	for name, runtime := range cases {
		t.Run(name, func(t *testing.T) {
			document := `{"items":[{"session_id":"s-1","filename":"s-1.42.session.stdout",` +
				`"is_task":false,"runtime":` + runtime + `}],"total":1}`
			key := "workspace\x00list\x00--json\x00--local\x00-s\x00s-1\x00--include-runtime"
			r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{key: answer(document)}}
			response := fixedProvider(r).dispatch(context.Background(), queryRequest(
				querySessionMetrics, &target{ResourceKind: resourceSession, ProviderResourceKey: "s-1"}, `{}`))
			if response.OK || response.Error == nil {
				t.Fatalf("response=%+v, want a provider failure", response)
			}
			if response.Error.Code == providerSessionNotFoundCode {
				t.Fatalf("an unmeasured session must not be reported as missing")
			}
		})
	}
}

// TestSessionMetricsRejectsNonOKStateWithData proves a non-ok state is refused
// even when the record still carries a payload.
//
// The provider reports an instruction that answered with its own failure as
// `state=unavailable` while keeping the raw payload for diagnosis
// (workspace_runtime.py:126-127). That payload has `ok=false`, so a reader that
// checked only the payload would report "no active agent" for a session whose
// process answered perfectly well. The state is the authority, and this test
// pins the message so the two failures cannot collapse into one.
func TestSessionMetricsRejectsNonOKStateWithData(t *testing.T) {
	document := `{"items":[{"session_id":"s-1","filename":"s-1.42.session.stdout",` +
		`"is_task":false,"runtime":{"state":"unavailable","error_code":"no_data","pid":42,` +
		`"data":{"ok":false,"error":"no_data"}}}],"total":1}`
	key := "workspace\x00list\x00--json\x00--local\x00-s\x00s-1\x00--include-runtime"
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{key: answer(document)}}
	response := fixedProvider(r).dispatch(context.Background(), queryRequest(
		querySessionMetrics, &target{ResourceKind: resourceSession, ProviderResourceKey: "s-1"}, `{}`))
	if response.OK || response.Error == nil {
		t.Fatalf("response=%+v, want a provider failure", response)
	}
	if response.Error.Message != "provider did not report runtime message counts" {
		t.Fatalf("message=%q, want the runtime-record failure rather than the agent failure",
			response.Error.Message)
	}
}

// TestSessionMetricsPrefersSessionRowOverTaskRow proves a task row never shadows
// the session row that actually owns the control channel.
//
// A session and its task children share one session identifier, but a task row is
// a child process log whose runtime record is reported as unsupported. Selecting
// it would report "no runtime data" for a session that answered perfectly well.
func TestSessionMetricsPrefersSessionRowOverTaskRow(t *testing.T) {
	document := `{"items":[` +
		`{"session_id":"s-1","filename":"s-1.42.task.stdout","is_task":true,` +
		`"runtime":{"state":"unavailable","error_code":"unsupported_row","pid":42,"data":null}},` +
		`{"session_id":"s-1","filename":"s-1.42.session.stdout","is_task":false,` +
		`"runtime":{"state":"ok","error_code":"","pid":42,"data":{"ok":true,` +
		`"agent2llm":{"messages":7},"user2agent":{"messages":3}}}}],"total":2}`
	key := "workspace\x00list\x00--json\x00--local\x00-s\x00s-1\x00--include-runtime"
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{key: answer(document)}}
	response := fixedProvider(r).dispatch(context.Background(), queryRequest(
		querySessionMetrics, &target{ResourceKind: resourceSession, ProviderResourceKey: "s-1"}, `{}`))
	if !response.OK || len(response.QueryResult) == 0 {
		t.Fatalf("response=%+v", response)
	}
	var result metricsResult
	if err := json.Unmarshal(response.QueryResult, &result); err != nil {
		t.Fatal(err)
	}
	if result.Messages.Inbound != 3 || result.Messages.Outbound != 7 {
		t.Fatalf("messages=%+v, want inbound=3 outbound=7", result.Messages)
	}
}

// TestSessionMetricsBatchReadsEverySessionInOneCall proves a set read costs one
// provider call regardless of how many sessions are asked about.
//
// The scripted runner fails on any unexpected argv and records every call, so the
// call count is the assertion. A per-session implementation would issue one call
// per session and fail here, which is the whole point of the batch: the provider's
// cost is a fixed task-directory scan, so paying it once per set instead of once
// per session is the only real saving.
//
// The argv is pinned without `-s` on purpose. The selector filters returned rows
// but does not avoid the scan (measured 652 ms for one row against 681 ms for all
// rows), so passing it would add argv length without saving work.
func TestSessionMetricsBatchReadsEverySessionInOneCall(t *testing.T) {
	document := `{"items":[` +
		`{"session_id":"s-1","filename":"s-1.42.session.stdout","is_task":false,` +
		`"runtime":{"state":"ok","error_code":"","pid":42,"data":{"ok":true,` +
		`"agent2llm":{"messages":68},"user2agent":{"messages":2}}}},` +
		`{"session_id":"s-2","filename":"s-2.43.session.stdout","is_task":false,` +
		`"runtime":{"state":"ok","error_code":"","pid":43,"data":{"ok":true,` +
		`"agent2llm":{"messages":7},"user2agent":{"messages":3}}}}],"total":2}`
	key := "workspace\x00list\x00--json\x00--local\x00--include-runtime"
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{key: answer(document)}}
	response := fixedProvider(r).dispatch(context.Background(), queryRequest(
		querySessionMetricsBatch, nil, `{"provider_session_ids":["s-1","s-2"]}`))
	if !response.OK || len(response.QueryResult) == 0 {
		t.Fatalf("response=%+v", response)
	}
	if len(r.calls) != 1 {
		t.Fatalf("provider calls=%d, want exactly 1 for a set read", len(r.calls))
	}
	var result metricsBatchResult
	if err := json.Unmarshal(response.QueryResult, &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Results) != 2 {
		t.Fatalf("results=%d, want 2", len(result.Results))
	}
	// The human listed user2agent first, so inbound is the operator side and
	// outbound is the model side, exactly as the single-session read maps them.
	bySession := map[string]messageCountsFact{}
	for _, member := range result.Results {
		bySession[member.ProviderSessionID] = member.Messages
	}
	if got := bySession["s-1"]; got.Inbound != 2 || got.Outbound != 68 {
		t.Fatalf("s-1 messages=%+v, want inbound=2 outbound=68", got)
	}
	if got := bySession["s-2"]; got.Inbound != 3 || got.Outbound != 7 {
		t.Fatalf("s-2 messages=%+v, want inbound=3 outbound=7", got)
	}
	if result.ObservedAtMS != 1700000000123 {
		t.Fatalf("observed_at_ms=%d", result.ObservedAtMS)
	}
}

// TestSessionMetricsBatchOmitsUnmeasuredSessions proves an unmeasurable member is
// absent from the result rather than present with a zero count.
//
// A zero is a measured zero. A session whose process never answered has not been
// measured, so filling it with zeros would state a fact the provider never
// observed. Absence is the contract's way of saying "not answered", and this test
// pins that the two outcomes stay distinguishable while the measurable neighbours
// are still reported.
func TestSessionMetricsBatchOmitsUnmeasuredSessions(t *testing.T) {
	document := `{"items":[` +
		`{"session_id":"s-1","filename":"s-1.42.session.stdout","is_task":false,` +
		`"runtime":{"state":"ok","error_code":"","pid":42,"data":{"ok":true,` +
		`"agent2llm":{"messages":68},"user2agent":{"messages":2}}}},` +
		`{"session_id":"s-2","filename":"s-2.43.session.stdout","is_task":false,` +
		`"runtime":{"state":"rejected","error_code":"control_rejected","pid":43,"data":null}}],"total":2}`
	key := "workspace\x00list\x00--json\x00--local\x00--include-runtime"
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{key: answer(document)}}
	response := fixedProvider(r).dispatch(context.Background(), queryRequest(
		querySessionMetricsBatch, nil, `{"provider_session_ids":["s-1","s-2","s-3"]}`))
	if !response.OK || len(response.QueryResult) == 0 {
		t.Fatalf("response=%+v", response)
	}
	var result metricsBatchResult
	if err := json.Unmarshal(response.QueryResult, &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Results) != 1 {
		t.Fatalf("results=%+v, want only the measurable session", result.Results)
	}
	if result.Results[0].ProviderSessionID != "s-1" {
		t.Fatalf("reported session=%q, want s-1", result.Results[0].ProviderSessionID)
	}
}

// TestSessionMetricsBatchRejectsTarget proves the set read refuses a target.
//
// A target names one resource and this request names many, so accepting both
// would leave the provider deciding which one wins. The refusal keeps one
// addressing form per request, exactly as launch.options refuses a target.
func TestSessionMetricsBatchRejectsTarget(t *testing.T) {
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	response := fixedProvider(r).dispatch(context.Background(), queryRequest(
		querySessionMetricsBatch, &target{ResourceKind: resourceSession, ProviderResourceKey: "s-1"},
		`{"provider_session_ids":["s-1"]}`))
	if response.OK || response.Error == nil {
		t.Fatalf("response=%+v, want a refusal", response)
	}
	if response.Error.Code != "invalid_request" {
		t.Fatalf("code=%q, want invalid_request", response.Error.Code)
	}
	if len(r.calls) != 0 {
		t.Fatalf("provider calls=%d, want none before the payload is accepted", len(r.calls))
	}
}

// TestSessionMetricsBatchRejectsEmptyAndOversizedSets proves the set is bounded
// before any provider process starts.
//
// The set is caller-supplied, so without a bound one request could ask about every
// session the provider has ever recorded and force an unbounded document. Both
// refusals must happen before the provider is invoked, which the call count proves.
func TestSessionMetricsBatchRejectsEmptyAndOversizedSets(t *testing.T) {
	oversized := make([]string, maxMetricsBatchSessions+1)
	for index := range oversized {
		oversized[index] = "s-" + strconv.Itoa(index)
	}
	oversizedPayload, err := json.Marshal(map[string][]string{"provider_session_ids": oversized})
	if err != nil {
		t.Fatal(err)
	}
	cases := map[string]string{
		"empty":     `{"provider_session_ids":[]}`,
		"oversized": string(oversizedPayload),
	}
	for name, payload := range cases {
		t.Run(name, func(t *testing.T) {
			r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
			response := fixedProvider(r).dispatch(context.Background(), queryRequest(
				querySessionMetricsBatch, nil, payload))
			if response.OK || response.Error == nil {
				t.Fatalf("response=%+v, want a refusal", response)
			}
			if response.Error.Code != "invalid_request" {
				t.Fatalf("code=%q, want invalid_request", response.Error.Code)
			}
			if len(r.calls) != 0 {
				t.Fatalf("provider calls=%d, want none for a refused set", len(r.calls))
			}
		})
	}
}

// TestSessionMetricsBatchDeduplicatesRepeatedSessions proves a repeated identifier
// is reported once.
//
// The Cluster contract rejects duplicates in a result, so a provider that echoed a
// repeated request member would produce a document the Cluster refuses. Collapsing
// the repeat keeps the result valid without silently dropping a distinct session.
func TestSessionMetricsBatchDeduplicatesRepeatedSessions(t *testing.T) {
	document := `{"items":[{"session_id":"s-1","filename":"s-1.42.session.stdout","is_task":false,` +
		`"runtime":{"state":"ok","error_code":"","pid":42,"data":{"ok":true,` +
		`"agent2llm":{"messages":68},"user2agent":{"messages":2}}}}],"total":1}`
	key := "workspace\x00list\x00--json\x00--local\x00--include-runtime"
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{key: answer(document)}}
	response := fixedProvider(r).dispatch(context.Background(), queryRequest(
		querySessionMetricsBatch, nil, `{"provider_session_ids":["s-1","s-1"]}`))
	if !response.OK || len(response.QueryResult) == 0 {
		t.Fatalf("response=%+v", response)
	}
	var result metricsBatchResult
	if err := json.Unmarshal(response.QueryResult, &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Results) != 1 {
		t.Fatalf("results=%+v, want one member for a repeated identifier", result.Results)
	}
}

// TestSessionDetailForwardsProviderRecordVerbatim proves the metadata section is
// the provider's own session record, unchanged.
//
// The Cluster deliberately does not model that record: it is provider detail and
// it changes when the provider changes. Forwarding the document keeps the surface
// honest, so this test compares the whole string rather than selected fields. A
// Cluster type built from the provider's fields would pass a field-level check
// while silently dropping every field it did not model.
func TestSessionDetailForwardsProviderRecordVerbatim(t *testing.T) {
	record := `{"session_id":"s-1","session_name":"demo","task":"work","status":"Idle","` +
		`project_workspace":"/work/demo","create_time":"2026-11-15T09:12:23","total_tokens":1234}`
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"session\x00info\x00s-1\x00--json": answer(record)}}
	response := fixedProvider(r).dispatch(context.Background(), queryRequest(
		querySessionDetail, &target{ResourceKind: resourceSession, ProviderResourceKey: "s-1"}, `{}`))
	if !response.OK || len(response.QueryResult) == 0 {
		t.Fatalf("response=%+v", response)
	}
	var result detailResult
	if err := json.Unmarshal(response.QueryResult, &result); err != nil {
		t.Fatal(err)
	}
	if result.Metadata != record {
		t.Fatalf("metadata=%q, want the provider record verbatim", result.Metadata)
	}
	// Runtime is the reserved seam. This provider reports nothing for it, so an
	// empty value is the correct answer and a placeholder would be a lie.
	if result.Runtime != "" {
		t.Fatalf("runtime=%q, want empty until a provider fills it", result.Runtime)
	}
}

// TestSessionDetailReportsMissingSessionFromStdout proves the not-found document
// is read before the exit status.
//
// The provider prints `{"error_code":"session_not_found"}` on stdout and exits
// non-zero. Reading the exit status first would report a missing session as a
// provider failure, which sends the operator to the wrong problem: the session
// does not exist, and nothing about the provider is broken.
func TestSessionDetailReportsMissingSessionFromStdout(t *testing.T) {
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"session\x00info\x00s-1\x00--json": {{stdout: `{"error_code":"session_not_found"}`, err: errors.New("exit status 1")}}}}
	response := fixedProvider(r).dispatch(context.Background(), queryRequest(
		querySessionDetail, &target{ResourceKind: resourceSession, ProviderResourceKey: "s-1"}, `{}`))
	if response.OK || response.Error == nil {
		t.Fatalf("response=%+v", response)
	}
	if response.Error.Code != providerSessionNotFoundCode {
		t.Fatalf("code=%q, want %q", response.Error.Code, providerSessionNotFoundCode)
	}
}

// TestSessionReadsRejectAnUnscopedTarget proves both new reads refuse a target
// that does not name a session.
//
// A session with no live process is absent from the inventory, so it has no
// Cluster resource ID and both reads address it by the provider's own identifier.
// An empty identifier must fail before any provider process starts, because a
// provider call with no session would either fail slowly or, worse, answer about
// whatever session the provider happens to consider current.
func TestSessionReadsRejectAnUnscopedTarget(t *testing.T) {
	for _, query := range []string{querySessionMetrics, querySessionDetail} {
		t.Run(query, func(t *testing.T) {
			r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
			response := fixedProvider(r).dispatch(context.Background(), queryRequest(
				query, &target{ResourceKind: resourceSession, ProviderResourceKey: "  "}, `{}`))
			if response.OK || response.Error == nil {
				t.Fatalf("response=%+v", response)
			}
			if response.Error.Code != "invalid_request" {
				t.Fatalf("code=%q, want invalid_request", response.Error.Code)
			}
			if len(r.calls) != 0 {
				t.Fatalf("provider was invoked with an unscoped target: %v", r.calls)
			}
		})
	}
}
