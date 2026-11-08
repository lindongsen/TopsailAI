package tui

import (
	"fmt"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestParseLogsArgsAcceptsSupportedForms covers every accepted spelling of the
// line limit together with the optional session token.
func TestParseLogsArgsAcceptsSupportedForms(t *testing.T) {
	const fallback = 424242
	const limit = 313131
	const token = "20261027152208"

	cases := []struct {
		name       string
		rest       string
		wantTok    string
		wantLine   int
		wantFollow bool
	}{
		{"empty keeps fallback", "", "", fallback, false},
		{"short flag", "-n " + fmt.Sprint(limit), "", limit, false},
		{"long flag", "--lines " + fmt.Sprint(limit), "", limit, false},
		{"equals form", "--lines=" + fmt.Sprint(limit), "", limit, false},
		{"token only", token, token, fallback, false},
		{"flag then token", "-n " + fmt.Sprint(limit) + " " + token, token, limit, false},
		{"token then flag", token + " --lines=" + fmt.Sprint(limit), token, limit, false},
		{"short follow", "-f", "", fallback, true},
		{"long follow", "--follow", "", fallback, true},
		{"follow with limit", "-f -n " + fmt.Sprint(limit), "", limit, true},
		{"follow with token", "--follow " + token, token, fallback, true},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			gotTok, gotLine, gotFollow, err := parseLogsArgs(tc.rest, fallback)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if gotTok != tc.wantTok {
				t.Fatalf("token=%q want=%q", gotTok, tc.wantTok)
			}
			if gotLine != tc.wantLine {
				t.Fatalf("lines=%d want=%d", gotLine, tc.wantLine)
			}
			if gotFollow != tc.wantFollow {
				t.Fatalf("follow=%t want=%t", gotFollow, tc.wantFollow)
			}
		})
	}
}

// TestParseLogsArgsKeepsFallbackWhenAbsent proves the default survives when no
// limit is supplied.
func TestParseLogsArgsKeepsFallbackWhenAbsent(t *testing.T) {
	const fallback = 515151
	_, gotLine, _, err := parseLogsArgs("", fallback)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if gotLine != fallback {
		t.Fatalf("lines=%d want=%d", gotLine, fallback)
	}
}

// TestParseLogsArgsRejectsInvalidInput proves malformed input fails loudly
// instead of silently falling back to the default.
func TestParseLogsArgsRejectsInvalidInput(t *testing.T) {
	bad := []string{
		"-n",
		"--lines",
		"-n abc",
		"-n 0",
		"-n -5",
		"--lines=",
		"--lines=x",
		"--unknown 909090",
		"tok1 tok2",
		"-f -f",
		"--follow --follow",
	}

	for _, rest := range bad {
		t.Run(rest, func(t *testing.T) {
			if _, _, _, err := parseLogsArgs(rest, 616161); err == nil {
				t.Fatalf("expected error for %q", rest)
			}
		})
	}
}

// TestTrimTailLinesBoundsOutput proves only the newest lines survive and that
// clipping is reported.
func TestTrimTailLinesBoundsOutput(t *testing.T) {
	source := []string{"alpha", "beta", "gamma", "delta", "epsilon"}
	keep := len(source) - len(source)/len(source)*2 // exactly three fewer than total

	content := strings.Join(source, "\n") + "\n"
	want := strings.Join(source[len(source)-keep:], "\n") + "\n"

	got, clipped := TrimTailLines(content, keep)
	if !clipped {
		t.Fatal("expected clipped=true")
	}
	if got != want {
		t.Fatalf("got=%q want=%q", got, want)
	}
}

// TestTrimTailLinesLeavesShortContentAlone proves content that already fits is
// returned byte-identical and unflagged.
func TestTrimTailLinesLeavesShortContentAlone(t *testing.T) {
	contents := []string{"", "single", "one\ntwo\n", "one\ntwo"}

	for _, content := range contents {
		got, clipped := TrimTailLines(content, 737373)
		if clipped {
			t.Fatalf("content=%q unexpectedly clipped", content)
		}
		if got != content {
			t.Fatalf("got=%q want=%q", got, content)
		}
	}
}

// TestTrimTailLinesDisabledWhenNonPositive proves a non-positive limit disables
// trimming entirely.
func TestTrimTailLinesDisabledWhenNonPositive(t *testing.T) {
	content := "one\ntwo\nthree\n"

	for _, limit := range []int{0, -848484} {
		got, clipped := TrimTailLines(content, limit)
		if clipped {
			t.Fatalf("limit=%d unexpectedly clipped", limit)
		}
		if got != content {
			t.Fatalf("limit=%d got=%q want=%q", limit, got, content)
		}
	}
}

// TestRenderSnapshotHonoursLineLimit proves the limit reaches the writer and
// flips the truncated marker.
func TestRenderSnapshotHonoursLineLimit(t *testing.T) {
	source := []string{"first", "second", "third", "fourth"}
	keep := len(source) - len(source)/len(source)*2

	var out strings.Builder
	RenderSnapshot(&out, 959595, strings.Join(source, "\n")+"\n", false, keep)
	rendered := out.String()

	if !strings.Contains(rendered, "truncated: true") {
		t.Fatalf("expected truncated marker, got=%q", rendered)
	}
	if strings.Contains(rendered, "first") {
		t.Fatalf("oldest line survived, got=%q", rendered)
	}
	if !strings.Contains(rendered, "fourth") {
		t.Fatalf("newest line missing, got=%q", rendered)
	}
}

// TestRenderSnapshotKeepsUpstreamTruncation proves an upstream truncation flag
// is never masked by an inactive line limit.
func TestRenderSnapshotKeepsUpstreamTruncation(t *testing.T) {
	var out strings.Builder
	RenderSnapshot(&out, 969696, "only\n", true, 979797)

	if !strings.Contains(out.String(), "truncated: true") {
		t.Fatalf("upstream flag lost, got=%q", out.String())
	}
}

// TestRenderReceiptDetailsPrintsPopulatedFields proves the durable receipt
// fields are surfaced after a send completes.
func TestRenderReceiptDetailsPrintsPopulatedFields(t *testing.T) {
	const commandID = "cli-989898"

	receipt := protocol.ExecutionReceipt{
		CommandID:        commandID,
		Phase:            protocol.PhaseReceiptRecorded,
		DeliveryBoundary: protocol.DeliverySubmitted,
		EffectCertainty:  protocol.EffectAcknowledged,
		Outcome:          "sent",
		ErrorCode:        "none",
		ErrorMessage:     "detail",
	}

	var out strings.Builder
	if err := renderReceiptDetails(&out, receipt); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	wanted := []string{
		"command_id: " + commandID,
		"phase: " + string(protocol.PhaseReceiptRecorded),
		"delivery_boundary: " + string(protocol.DeliverySubmitted),
		"effect_certainty: " + string(protocol.EffectAcknowledged),
		"outcome: sent",
		"error_code: none",
		"error_message: detail",
	}

	for _, want := range wanted {
		if !strings.Contains(out.String(), want) {
			t.Fatalf("missing %q in %q", want, out.String())
		}
	}
}

// TestRenderReceiptDetailsSkipsEmptyFields proves sparse receipts stay quiet
// instead of printing empty placeholders.
func TestRenderReceiptDetailsSkipsEmptyFields(t *testing.T) {
	var out strings.Builder
	if err := renderReceiptDetails(&out, protocol.ExecutionReceipt{}); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if out.String() != "" {
		t.Fatalf("expected no output, got=%q", out.String())
	}
}

// TestLogsForwardsParsedLineCountToAPI proves the line limit parsed from the
// interactive command reaches the API request instead of only trimming the
// rendered text, which is the defect this test guards. Entering the session
// already renders one bounded snapshot, so the explicit logs read is the second
// request and must carry its own parsed limit.
func TestLogsForwardsParsedLineCountToAPI(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  int
	}{
		{name: "short flag", input: "cd host-one/endpoint-1/res-1\nlogs -n 250\nexit\n", want: 250},
		{name: "long flag", input: "cd host-one/endpoint-1/res-1\nlogs --lines 7\nexit\n", want: 7},
		{name: "equals form", input: "cd host-one/endpoint-1/res-1\nlogs --lines=33\nexit\n", want: 33},
		{name: "absent keeps interactive default", input: "cd host-one/endpoint-1/res-1\nlogs\nexit\n", want: DefaultInteractiveMaxLines},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := scopeStub()
			if _, diagnostics := runScope(t, stub, testCase.input, ColorPolicy{}); diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if len(stub.outputRequests) != 2 {
				t.Fatalf("output requests=%+v", stub.outputRequests)
			}
			if got := stub.outputRequests[0].maxLines; got != DefaultInteractiveMaxLines {
				t.Fatalf("automatic entry snapshot maxLines=%d want=%d", got, DefaultInteractiveMaxLines)
			}
			if got := stub.outputRequests[1].maxLines; got != testCase.want {
				t.Fatalf("maxLines=%d want=%d", got, testCase.want)
			}
		})
	}
}
