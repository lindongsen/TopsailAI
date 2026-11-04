package tui

import (
	"bufio"
	"errors"
	"io"
	"strings"
	"testing"
)

// TestLineKeysSupported checks common terminal and control-key encodings.
func TestLineKeysSupported(t *testing.T) {
	cases := []struct {
		input string
		kind  lineKeyKind
	}{
		{"\r", lineKeyEnter}, {"\n", lineKeyEnter}, {"\b", lineKeyBackspace}, {"\x7f", lineKeyBackspace},
		{"\x01", lineKeyHome}, {"\x05", lineKeyEnd}, {"\x02", lineKeyLeft}, {"\x06", lineKeyRight},
		{"\x10", lineKeyPrevious}, {"\x0e", lineKeyNext}, {"\x03", lineKeyInterrupt}, {"\x04", lineKeyEOF},
		{"\x1b[A", lineKeyPrevious}, {"\x1b[B", lineKeyNext}, {"\x1b[C", lineKeyRight}, {"\x1b[D", lineKeyLeft},
		{"\x1b[H", lineKeyHome}, {"\x1b[F", lineKeyEnd}, {"\x1b[1~", lineKeyHome}, {"\x1b[7~", lineKeyHome},
		{"\x1b[4~", lineKeyEnd}, {"\x1b[8~", lineKeyEnd}, {"\x1b[3~", lineKeyDelete},
		{"\x1bOA", lineKeyPrevious}, {"\x1bOB", lineKeyNext}, {"\x1bOC", lineKeyRight},
		{"\x1bOD", lineKeyLeft}, {"\x1bOH", lineKeyHome}, {"\x1bOF", lineKeyEnd},
	}
	for _, c := range cases {
		t.Run(c.input, func(t *testing.T) {
			got, err := readLineKey(bufio.NewReader(strings.NewReader(c.input)))
			if err != nil || got.kind != c.kind || got.text != 0 {
				t.Fatalf("key=%+v err=%v", got, err)
			}
		})
	}
}

// TestLineKeysUnicode preserves rune ordering and reports EOF separately.
func TestLineKeysUnicode(t *testing.T) {
	reader := bufio.NewReader(strings.NewReader("a中文�"))
	for _, r := range "a中文�" {
		got, err := readLineKey(reader)
		if err != nil || got.kind != lineKeyText || got.text != r {
			t.Fatalf("key=%+v err=%v", got, err)
		}
	}
	if _, err := readLineKey(reader); err != io.EOF {
		t.Fatal(err)
	}
}

// TestLineKeysRejectMalformed never converts escape payloads to printable keys.
func TestLineKeysRejectMalformed(t *testing.T) {
	for _, input := range []string{"\xff", "\t", "\x1bx", "\x1b[Z", "\x1b[200~", "\x1bO3~", "\x1b[\x00", "\x1b[\xff"} {
		if _, err := readLineKey(bufio.NewReader(strings.NewReader(input))); !errors.Is(err, errLineKey) {
			t.Fatalf("input=%q err=%v", input, err)
		}
	}
	for _, input := range []string{"\x1b", "\x1b[", "\x1bO", "\x1b[123"} {
		_, err := readLineKey(bufio.NewReader(strings.NewReader(input)))
		if !errors.Is(err, errLineKey) || !errors.Is(err, io.ErrUnexpectedEOF) {
			t.Fatalf("input=%q err=%v", input, err)
		}
	}
}

// TestLineKeysSequenceBound caps work even with an arbitrarily long CSI payload.
func TestLineKeysSequenceBound(t *testing.T) {
	reader := bufio.NewReader(strings.NewReader("\x1b[" + strings.Repeat("1", maxLineKeySequence) + "tail"))
	if _, err := readLineKey(reader); !errors.Is(err, errLineKey) {
		t.Fatal(err)
	}
	remaining, err := io.ReadAll(reader)
	if err != nil || string(remaining) != "tail" {
		t.Fatalf("remaining=%q err=%v", remaining, err)
	}
	reader = bufio.NewReader(strings.NewReader("\x1b[" + strings.Repeat("1", maxLineKeySequence-1) + "~"))
	if _, err := readLineKey(reader); !errors.Is(err, errLineKey) {
		t.Fatal(err)
	}
}

// keyFailureReader exposes an exact underlying read failure.
type keyFailureReader struct{ err error }

// Read always returns the injected failure without creating any resources.
func (r keyFailureReader) Read([]byte) (int, error) { return 0, r.err }

// TestLineKeysReadFailure retains failure identity at every escape boundary.
func TestLineKeysReadFailure(t *testing.T) {
	sentinel := errors.New("input failed")
	for _, prefix := range []string{"", "\x1b", "\x1b["} {
		reader := bufio.NewReader(io.MultiReader(strings.NewReader(prefix), keyFailureReader{sentinel}))
		if _, err := readLineKey(reader); !errors.Is(err, sentinel) {
			t.Fatalf("prefix=%q err=%v", prefix, err)
		}
	}
}
