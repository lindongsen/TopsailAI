package tui

import (
	"bytes"
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func TestInteractiveContinuesAfterRecoveredCommandFailure(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}, failList: true}
	var output, errorsOut strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader("list\nhelp\nquit\n"), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(errorsOut.String(), "temporary list failure") {
		t.Fatalf("missing recovered failure: %q", errorsOut.String())
	}
	if !strings.Contains(output.String(), "commands:") {
		t.Fatalf("loop did not continue to help: %q", output.String())
	}
}

func TestInteractiveExitAliasesReturnAfterPrompt(t *testing.T) {
	for _, command := range []string{"quit\n", "exit\n", ""} {
		var output, errorsOut strings.Builder
		if err := RunInteractive(context.Background(), &interactiveStub{}, strings.NewReader(command), &output, &errorsOut, InteractiveOptions{}); err != nil {
			t.Fatalf("command %q: %v", command, err)
		}
	}
}

func TestSafeWriterDoesNotLeakControlsAcrossWrites(t *testing.T) {
	var output strings.Builder
	writer := newSafeWriter(&output)
	if _, err := writer.Write([]byte("prefix\x1b")); err != nil {
		t.Fatal(err)
	}
	if _, err := writer.Write([]byte("[31msecret\r\n")); err != nil {
		t.Fatal(err)
	}
	if strings.ContainsAny(output.String(), "\x1b\r") {
		t.Fatalf("control sequence leaked across writes: %q", output.String())
	}
}

func TestSafeWriterPreservesChunkedUTF8(t *testing.T) {
	input := "ASCII caf\u00e9 \u4e16\u754c \U0001f44b e\u0301\n\tend"
	for width := 1; width <= 3; width++ {
		var output strings.Builder
		writer := newSafeWriter(&output)
		for offset := 0; offset < len(input); {
			end := offset + width
			if end > len(input) {
				end = len(input)
			}
			if _, err := writer.Write([]byte(input[offset:end])); err != nil {
				t.Fatal(err)
			}
			offset = end
		}
		if err := writer.Flush(); err != nil {
			t.Fatal(err)
		}
		if output.String() != input {
			t.Fatalf("width %d output=%q want=%q", width, output.String(), input)
		}
	}
}

func TestSafeWriterFiltersSplitCSIAndOSC(t *testing.T) {
	for _, testCase := range []struct {
		input string
		want  string
	}{
		{"before\x1b[31msecret", "beforesecret"},
		{"before\x1b]0;title\aafter", "beforeafter"},
		{"before\x1b]8;;url\x1b\\after", "beforeafter"},
	} {
		for split := 0; split <= len(testCase.input); split++ {
			var output strings.Builder
			writer := newSafeWriter(&output)
			if _, err := writer.Write([]byte(testCase.input[:split])); err != nil {
				t.Fatal(err)
			}
			if _, err := writer.Write([]byte(testCase.input[split:])); err != nil {
				t.Fatal(err)
			}
			if err := writer.Flush(); err != nil {
				t.Fatal(err)
			}
			if output.String() != testCase.want {
				t.Fatalf("input %q split %d output=%q want=%q", testCase.input, split, output.String(), testCase.want)
			}
		}
	}
}

func TestSafeWriterFlushDropsIncompleteSequenceAndFiltersBidi(t *testing.T) {
	var output strings.Builder
	writer := newSafeWriter(&output)
	if _, err := writer.Write([]byte("ok\x1b]0;unterminated")); err != nil {
		t.Fatal(err)
	}
	if err := writer.Flush(); err != nil {
		t.Fatal(err)
	}
	bidi := string([]rune{0x202a, 0x202b, 0x202c, 0x202d, 0x202e, 0x2066, 0x2067, 0x2068, 0x2069, 0x200e, 0x200f, 0x061c})
	if _, err := writer.Write([]byte(bidi + "done")); err != nil {
		t.Fatal(err)
	}
	if err := writer.Flush(); err != nil {
		t.Fatal(err)
	}
	if output.String() != "okdone" {
		t.Fatalf("output=%q want=%q", output.String(), "okdone")
	}
	if writer.sequenceSize != 0 || writer.state != terminalNormal || len(writer.utf8Pending) != 0 {
		t.Fatalf("state not flushed: state=%d sequence=%d pending=%d", writer.state, writer.sequenceSize, len(writer.utf8Pending))
	}
}

func TestSafeWriterBoundsUnterminatedSequence(t *testing.T) {
	var output strings.Builder
	writer := newSafeWriter(&output)
	data := append([]byte("prefix\x1b]"), bytes.Repeat([]byte{'x'}, 10000)...)
	if _, err := writer.Write(data); err != nil {
		t.Fatal(err)
	}
	if writer.sequenceSize > maxTerminalSequenceBytes {
		t.Fatalf("sequence size=%d exceeds limit", writer.sequenceSize)
	}
	if err := writer.Flush(); err != nil {
		t.Fatal(err)
	}
	if output.String() != "prefix" {
		t.Fatalf("unexpected bounded output=%q", output.String())
	}
}
