package providercli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// structJSONTags returns the JSON field names declared by one struct in a Go
// source file. Reading the struct rather than listing the names here means a
// field added to ImmutableIntent is covered by this guard without an edit.
func structJSONTags(t *testing.T, relativePath, structName string) []string {
	t.Helper()
	root := filepath.Join(schemaDirectory(t), "..", "..", "..")
	source, err := os.ReadFile(filepath.Join(root, relativePath))
	if err != nil {
		t.Fatalf("read %s: %v", relativePath, err)
	}
	text := string(source)
	start := strings.Index(text, "type "+structName+" struct {")
	if start < 0 {
		t.Fatalf("%s declares no %s struct, so this guard checked nothing", relativePath, structName)
	}
	body := text[start:]
	if end := strings.Index(body, "\n}"); end >= 0 {
		body = body[:end]
	}
	tagPattern := regexp.MustCompile("`json:\"([a-z0-9_]+)")
	matches := tagPattern.FindAllStringSubmatch(body, -1)
	if len(matches) == 0 {
		t.Fatalf("%s %s declares no JSON field, so this guard checked nothing", relativePath, structName)
	}
	names := make([]string, 0, len(matches))
	for _, match := range matches {
		names = append(names, match[1])
	}
	return names
}

// requestWithField returns a valid request document carrying one extra root
// field, so a rejection can only come from that field.
func requestWithField(t *testing.T, function, field string, value any) []byte {
	t.Helper()
	encoded, err := json.Marshal(validRequest(function))
	if err != nil {
		t.Fatalf("marshal the base request: %v", err)
	}
	var document map[string]any
	if err := json.Unmarshal(encoded, &document); err != nil {
		t.Fatalf("unmarshal the base request: %v", err)
	}
	document[field] = value
	withField, err := json.Marshal(document)
	if err != nil {
		t.Fatalf("marshal the request with %q: %v", field, err)
	}
	return withField
}

// providerSideSharedFields are the ImmutableIntent names that legitimately
// appear on a provider request, each carrying a provider-side value rather than
// Cluster authority: target is a provider target, operation and payload are the
// standard contract and its typed payload, and budget is the provider budget.
//
// The list is explicit rather than "whatever the two structs happen to share".
// Skipping every shared name would silently accept a Cluster authority field the
// moment someone added it to Request, because it would then look shared.
var providerSideSharedFields = []string{"budget", "operation", "payload", "target"}

// TestClusterIntentFieldsAreRejectedAtRequestRoot fails when a field that
// belongs to a Cluster ImmutableIntent is accepted on the provider request.
//
// The contract states that the Adapter must not serialize a complete Cluster
// ImmutableIntent onto the provider process boundary. The request therefore
// carries a provider target, a standard function, a typed payload, a deadline
// and budgets, and nothing else. Four ImmutableIntent names do appear on the
// request, but they carry a different shape, and they are named explicitly
// above. Every other ImmutableIntent field must be refused as an unknown field.
func TestClusterIntentFieldsAreRejectedAtRequestRoot(t *testing.T) {
	intentFields := structJSONTags(t, "internal/protocol/command.go", "ImmutableIntent")
	requestFields := structJSONTags(t, "internal/providercli/types.go", "Request")
	requestSet := make(map[string]bool, len(requestFields))
	for _, field := range requestFields {
		requestSet[field] = true
	}
	allowed := make(map[string]bool, len(providerSideSharedFields))
	for _, field := range providerSideSharedFields {
		allowed[field] = true
	}

	// The shared set must be exactly the allowlist. A new shared name means
	// either a legitimate provider-side field that needs a documented reason
	// here, or a Cluster authority field that must be removed from Request.
	shared := make([]string, 0, len(providerSideSharedFields))
	for _, field := range intentFields {
		if requestSet[field] {
			shared = append(shared, field)
		}
	}
	if len(shared) != len(providerSideSharedFields) {
		t.Fatalf("the request and ImmutableIntent share %v, but the documented provider-side set is %v, so a shared name is unexplained", shared, providerSideSharedFields)
	}
	for _, field := range shared {
		if !allowed[field] {
			t.Fatalf("the request and ImmutableIntent share %q, which is not a documented provider-side field, so Cluster authority can cross into provider authority", field)
		}
	}

	checked := 0
	for _, field := range intentFields {
		if allowed[field] {
			continue
		}
		checked++
		_, err := DecodeRequest(requestWithField(t, FunctionDescribe, field, "cluster-owned"))
		if err == nil {
			t.Errorf("the request accepts the ImmutableIntent field %q, so Cluster intent can cross into provider authority", field)
			continue
		}
		if !strings.Contains(err.Error(), "unknown field") {
			t.Errorf("the request rejects the ImmutableIntent field %q for an unrelated reason (%v), so the rejection is not the one this row requires", field, err)
		}
	}
	if checked == 0 {
		t.Fatal("no ImmutableIntent field was outside the provider-side set, so this guard checked nothing")
	}
}

// TestAuthorityFieldsAreRejectedAtRequestRoot fails when a field naming caller
// authority is accepted on the provider request. These names are not part of
// ImmutableIntent, so the previous test does not cover them.
func TestAuthorityFieldsAreRejectedAtRequestRoot(t *testing.T) {
	authorityFields := []string{"authority", "permissions", "caller", "granted_scope", "caller_identity"}
	if len(authorityFields) == 0 {
		t.Fatal("no authority field was enumerated, so this guard checked nothing")
	}
	for _, field := range authorityFields {
		_, err := DecodeRequest(requestWithField(t, FunctionDescribe, field, map[string]any{"scope": "admin"}))
		if err == nil {
			t.Errorf("the request accepts the authority field %q, so caller authority can cross into provider authority", field)
			continue
		}
		if !strings.Contains(err.Error(), "unknown field") {
			t.Errorf("the request rejects the authority field %q for an unrelated reason (%v), so the rejection is not the one this row requires", field, err)
		}
	}
}

// TestClusterShapedTargetAndOperationAreRejected fails when a Cluster-shaped
// target or operation is accepted. The names target and operation do appear on
// the request, so the previous tests skip them; what must be refused is the
// Cluster shape inside them, which carries resource_id and capability_revision
// instead of a provider key and a contract version.
//
// Each Cluster field is probed on its own. Sending the whole Cluster object
// would pass as soon as any one of its fields is unknown, so a field that
// became legal would be hidden behind its neighbours.
func TestClusterShapedTargetAndOperationAreRejected(t *testing.T) {
	providerTarget := map[string]any{
		"resource_kind":         "session",
		"provider_resource_key": "provider-session-1",
	}
	clusterTargetFields := []string{"kind", "resource_id", "provider_generation"}
	if len(clusterTargetFields) == 0 {
		t.Fatal("no Cluster target field was enumerated, so this guard checked nothing")
	}
	for _, field := range clusterTargetFields {
		target := map[string]any{}
		for key, value := range providerTarget {
			target[key] = value
		}
		target[field] = "cluster-owned"
		_, err := DecodeRequest(requestWithField(t, FunctionInspect, "target", target))
		if err == nil {
			t.Errorf("the request accepts the Cluster target field %q, so a Cluster resource identity can cross into provider authority", field)
			continue
		}
		if !strings.Contains(err.Error(), "unknown field") {
			t.Errorf("the request rejects the Cluster target field %q for an unrelated reason (%v), so the rejection is not the one this row requires", field, err)
		}
	}

	providerOperation := map[string]any{
		"name":    "ctl.heartbeat",
		"version": "v1",
	}
	clusterOperationFields := []string{"operation_version", "capability_revision", "payload_schema_version"}
	if len(clusterOperationFields) == 0 {
		t.Fatal("no Cluster operation field was enumerated, so this guard checked nothing")
	}
	for _, field := range clusterOperationFields {
		operation := map[string]any{}
		for key, value := range providerOperation {
			operation[key] = value
		}
		operation[field] = "cluster-owned"
		_, err := DecodeRequest(requestWithField(t, FunctionExecute, "operation", operation))
		if err == nil {
			t.Errorf("the request accepts the Cluster operation field %q, so Cluster command identity can cross into provider authority", field)
			continue
		}
		if !strings.Contains(err.Error(), "unknown field") {
			t.Errorf("the request rejects the Cluster operation field %q for an unrelated reason (%v), so the rejection is not the one this row requires", field, err)
		}
	}
}
