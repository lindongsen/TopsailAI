package tui

import (
	"strings"
	"testing"
)

// TestRenderStructuredBodyRendersObjectAsKeyValueLines proves a JSON object body
// is rendered as readable lines instead of braces and quotes.
//
// The fixture is the body an operator reported as unreadable: a single object with
// a text field and a label field. Printing it verbatim showed JSON to the operator,
// which is the defect this rendering exists to remove.
func TestRenderStructuredBodyRendersObjectAsKeyValueLines(t *testing.T) {
	body := `{
  "raw_text": "先更新到文档里面。",
  "step_name": "task"
}`
	got := renderStructuredBody(body)
	if strings.ContainsAny(got, "{}") {
		t.Fatalf("rendered body = %q, want no braces", got)
	}
	if strings.Contains(got, `"`) {
		t.Fatalf("rendered body = %q, want no quotes", got)
	}
	if !strings.Contains(got, "raw_text: 先更新到文档里面。") {
		t.Fatalf("rendered body = %q, want the text under its key", got)
	}
	if !strings.Contains(got, "step_name: task") {
		t.Fatalf("rendered body = %q, want the label under its key", got)
	}
}

// TestRenderStructuredBodySortsKeys proves the rendering is stable.
//
// Two reads of the same body must produce the same text, otherwise an operator
// comparing two reads would see a difference that is not a change in the data.
func TestRenderStructuredBodySortsKeys(t *testing.T) {
	first := renderStructuredBody(`{"zebra":"z","alpha":"a","middle":"m"}`)
	second := renderStructuredBody(`{"middle":"m","zebra":"z","alpha":"a"}`)
	if first != second {
		t.Fatalf("rendering is not stable: %q vs %q", first, second)
	}
	if !strings.HasPrefix(first, "alpha: a") {
		t.Fatalf("rendered body = %q, want keys sorted", first)
	}
}

// TestRenderStructuredBodyRendersScalarListAsBullets proves a list of scalars is
// rendered as a bulleted list rather than as a JSON array.
func TestRenderStructuredBodyRendersScalarListAsBullets(t *testing.T) {
	got := renderStructuredBody(`["first","second","third"]`)
	if strings.ContainsAny(got, "[]") {
		t.Fatalf("rendered body = %q, want no brackets", got)
	}
	for _, want := range []string{"- first", "- second", "- third"} {
		if !strings.Contains(got, want) {
			t.Fatalf("rendered body = %q, want %q", got, want)
		}
	}
}

// TestRenderStructuredBodyNumbersObjectList proves a list of objects is rendered
// as numbered blocks, so an operator can refer to one record.
func TestRenderStructuredBodyNumbersObjectList(t *testing.T) {
	got := renderStructuredBody(`[{"name":"one"},{"name":"two"}]`)
	// The numbered markers are the intended output, so only JSON punctuation is
	// forbidden here. Forbidding every bracket would reject the numbering that
	// lets an operator refer to one record.
	if strings.ContainsAny(got, "{}") {
		t.Fatalf("rendered body = %q, want no braces", got)
	}
	if strings.Contains(got, `"`) {
		t.Fatalf("rendered body = %q, want no quotes", got)
	}
	if !strings.Contains(got, "[1]") || !strings.Contains(got, "[2]") {
		t.Fatalf("rendered body = %q, want numbered blocks", got)
	}
	if !strings.Contains(got, "name: one") || !strings.Contains(got, "name: two") {
		t.Fatalf("rendered body = %q, want each record rendered", got)
	}
}

// TestRenderStructuredBodyIndentsNestedObject proves a nested object is indented
// under its key instead of being flattened into one line.
func TestRenderStructuredBodyIndentsNestedObject(t *testing.T) {
	got := renderStructuredBody(`{"outer":{"inner":"value"}}`)
	lines := strings.Split(got, "\n")
	if len(lines) < 2 {
		t.Fatalf("rendered body = %q, want the nested value on its own line", got)
	}
	if lines[0] != "outer:" {
		t.Fatalf("first line = %q, want the key alone", lines[0])
	}
	if !strings.HasPrefix(lines[1], messagesBodyIndent) {
		t.Fatalf("second line = %q, want it indented", lines[1])
	}
	if !strings.Contains(lines[1], "inner: value") {
		t.Fatalf("second line = %q, want the nested pair", lines[1])
	}
}

// TestRenderStructuredBodyKeepsProseVerbatim proves ordinary prose is untouched.
//
// Prose is the common case, so it must not be re-encoded, re-wrapped or trimmed.
// The provider's own layout is reproduced for prose, and that guarantee would be
// lost if this rendering touched it.
func TestRenderStructuredBodyKeepsProseVerbatim(t *testing.T) {
	const prose = "topsailai.task\n先更新到文档里面。\n\n第二段。"
	if got := renderStructuredBody(prose); got != prose {
		t.Fatalf("rendered body = %q, want the prose unchanged", got)
	}
}

// TestRenderStructuredBodyKeepsInvalidJSONVerbatim proves a body that no longer
// parses is shown as it is.
//
// A truncated body is exactly the case where the surviving text still matters, so
// replacing it with an error or an empty string would lose the only evidence the
// operator has.
func TestRenderStructuredBodyKeepsInvalidJSONVerbatim(t *testing.T) {
	const broken = `{"raw_text": "cut off mid`
	if got := renderStructuredBody(broken); got != broken {
		t.Fatalf("rendered body = %q, want the broken body unchanged", got)
	}
}

// TestRenderStructuredBodyKeepsScalarJSONVerbatim proves a bare JSON scalar is not
// rewritten, because it carries no structure to improve on.
func TestRenderStructuredBodyKeepsScalarJSONVerbatim(t *testing.T) {
	for _, body := range []string{`"just a string"`, `42`, `true`, `null`} {
		if got := renderStructuredBody(body); got != body {
			t.Fatalf("rendered body = %q, want %q unchanged", got, body)
		}
	}
}

// TestRenderStructuredBodyMarksEmptyContainers proves an empty object or array is
// stated rather than rendered as nothing.
//
// An empty body would otherwise be indistinguishable from a rendering failure, and
// the renderer already states an empty body explicitly for the same reason.
func TestRenderStructuredBodyMarksEmptyContainers(t *testing.T) {
	if got := renderStructuredBody(`{}`); got != "{}" {
		t.Fatalf("rendered body = %q, want the empty object kept", got)
	}
	if got := renderStructuredBody(`[]`); got != "[]" {
		t.Fatalf("rendered body = %q, want the empty array kept", got)
	}
}

// TestRenderStructuredBodyBoundsDepth proves a deeply nested body cannot produce
// unbounded indentation.
func TestRenderStructuredBodyBoundsDepth(t *testing.T) {
	body := `{"a":{"b":{"c":{"d":{"e":{"f":{"g":{"h":"deep"}}}}}}}}`
	got := renderStructuredBody(body)
	if !strings.Contains(got, "deep") {
		t.Fatalf("rendered body = %q, want the deepest value preserved", got)
	}
	for _, line := range strings.Split(got, "\n") {
		indent := len(line) - len(strings.TrimLeft(line, " "))
		if indent > messagesBodyMaxDepth*len(messagesBodyIndent) {
			t.Fatalf("line %q is indented %d spaces, want at most %d", line, indent, messagesBodyMaxDepth*len(messagesBodyIndent))
		}
	}
}

// TestRenderMessagesRendersStructuredBody proves the renderer applies the
// structured-body rule, so a JSON body never reaches the terminal as JSON.
//
// This is the composed path: the unit tests above prove the conversion, and this
// one proves the conversion is actually reached from the rendered conversation.
func TestRenderMessagesRendersStructuredBody(t *testing.T) {
	view := MessagesView{
		EndpointID:        "e1",
		ProviderSessionID: "s1",
		MessageCount:      1,
		Rows: []MessagesViewRow{{
			No:      1,
			Role:    "user",
			Content: `{"raw_text":"hello","step_name":"task"}`,
		}},
	}
	var out strings.Builder
	if err := RenderMessages(&out, view, ColorPolicy{}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	rendered := out.String()
	if strings.ContainsAny(rendered, "{}") {
		t.Fatalf("rendered = %q, want no braces", rendered)
	}
	if !strings.Contains(rendered, "raw_text: hello") {
		t.Fatalf("rendered = %q, want the body rendered as text", rendered)
	}
}
