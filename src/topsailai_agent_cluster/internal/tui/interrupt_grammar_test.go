package tui

import (
	"encoding/json"
	"strings"
	"testing"
)

// TestInterruptActionWordsAreExactlyTheDocumentedPair pins the CLI action word set
// to the two words the help advertises. An abbreviation or a wire name accepted as
// a CLI word is a second grammar for one concept, and the help would then describe
// only half of what the parser accepts. The wire names stay reachable inside the
// JSON advanced form, where they are the provider's own vocabulary.
//
// Case and surrounding space are not spellings: drive resolves its action word
// through the same lower-and-trim step, so accepting SOFT here keeps one convention
// rather than adding a second one.
func TestInterruptActionWordsAreExactlyTheDocumentedPair(t *testing.T) {
	for _, word := range []string{"soft", "hard", "SOFT", "Hard", " soft "} {
		if _, known := InterruptActionWord(word); !known {
			t.Fatalf("documented action word %q is not accepted", word)
		}
	}
	for _, word := range []string{"s", "h", "soft_interrupt", "hard_interrupt", "nope", ""} {
		if _, known := InterruptActionWord(word); known {
			t.Fatalf("undocumented action word %q is accepted", word)
		}
	}
}

// TestParseInterruptArgumentsRefusesUndocumentedSpellings proves the refusal is
// reachable from the shared parser both surfaces call, not only from the lookup
// helper. A message with no action word and a misspelled action word are the same
// shape, so the refusal must state the grammar instead of blaming one token.
func TestParseInterruptArgumentsRefusesUndocumentedSpellings(t *testing.T) {
	for _, word := range []string{"s", "h", "soft_interrupt", "hard_interrupt"} {
		_, _, err := ParseInterruptArguments([]string{word, "ep", "res"})
		if err == nil {
			t.Fatalf("action word %q was accepted", word)
		}
		if !strings.Contains(err.Error(), "quote the message so it stays one argument") {
			t.Fatalf("action word %q error=%v", word, err)
		}
	}
	action, message, err := ParseInterruptArguments([]string{"soft", "stop now"})
	if err != nil || action != "soft" || message != "stop now" {
		t.Fatalf("action=%q message=%q err=%v", action, message, err)
	}
}

// TestInterruptPayloadRefusesFieldsOutsideTheClosedSet proves the local surface
// rejects a field the provider's strict decoder would reject, so a typo costs a
// local error instead of a round trip that already asked for confirmation. The
// closed set is the provider's own two fields, and the refusal names the offending
// key so the typo is visible.
func TestInterruptPayloadRefusesFieldsOutsideTheClosedSet(t *testing.T) {
	for _, document := range []string{
		`{"action":"soft_interrupt","msg":"x"}`,
		`{"action":"soft_interrupt","Message":"x"}`,
		`{"action":"soft_interrupt","message":"x","extra":1}`,
	} {
		_, err := InterruptPayload("interrupt", "soft", document)
		if err == nil {
			t.Fatalf("document %s was accepted", document)
		}
		if !strings.Contains(err.Error(), "is not part of the interrupt payload") {
			t.Fatalf("document %s error=%v", document, err)
		}
	}
}

// TestInterruptPayloadAcceptsTheClosedSet proves the refusal above is not a blanket
// rejection: the two accepted fields still work, an empty object still receives the
// positional action word, and the wire action name is still accepted when it agrees
// with that word.
func TestInterruptPayloadAcceptsTheClosedSet(t *testing.T) {
	cases := []struct {
		name    string
		action  string
		message string
		want    string
	}{
		{name: "empty object receives the action word", action: "soft", message: `{}`, want: `{"action":"soft_interrupt"}`},
		{name: "wire action agrees with the word", action: "hard", message: `{"action":"hard_interrupt"}`, want: `{"action":"hard_interrupt"}`},
		{name: "message field is kept", action: "soft", message: `{"message":"stop now"}`, want: `{"action":"soft_interrupt","message":"stop now"}`},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			payload, err := InterruptPayload("interrupt", testCase.action, testCase.message)
			if err != nil {
				t.Fatal(err)
			}
			var decoded map[string]any
			if err := json.Unmarshal(payload, &decoded); err != nil {
				t.Fatalf("payload=%s err=%v", payload, err)
			}
			if len(decoded) != len(mustDecode(t, testCase.want)) {
				t.Fatalf("payload=%s want=%s", payload, testCase.want)
			}
			for field, want := range mustDecode(t, testCase.want) {
				if decoded[field] != want {
					t.Fatalf("payload=%s field %q=%v want %v", payload, field, decoded[field], want)
				}
			}
		})
	}
}

// TestInterruptPayloadRefusesACLIWordInsideTheDocument proves the two layers keep
// one spelling each. The command line carries the CLI word and the document carries
// the wire name, so a CLI word inside the document is refused rather than
// translated: translating it would let an operator believe the document is the
// command line, and the provider would then receive a value it never decodes.
func TestInterruptPayloadRefusesACLIWordInsideTheDocument(t *testing.T) {
	for _, document := range []string{`{"action":"soft"}`, `{"action":"hard"}`} {
		_, err := InterruptPayload("interrupt", "soft", document)
		if err == nil {
			t.Fatalf("document %s was accepted", document)
		}
		if !strings.Contains(err.Error(), "the document carries the wire action name") {
			t.Fatalf("document %s error=%v", document, err)
		}
	}
}

// mustDecode decodes one expected payload document for comparison.
func mustDecode(t *testing.T, document string) map[string]any {
	t.Helper()
	var decoded map[string]any
	if err := json.Unmarshal([]byte(document), &decoded); err != nil {
		t.Fatalf("decode %s: %v", document, err)
	}
	return decoded
}

// TestInterruptActionWordFeedsInterruptPayload proves the two exported helpers
// compose. The standalone command resolves the action word with InterruptActionWord
// and passes the result straight into InterruptPayload, so a helper that returned the
// wire name made every interrupt fail with a usage error while each helper passed its
// own test. Only the composition shows that, which is why it is asserted here.
func TestInterruptActionWordFeedsInterruptPayload(t *testing.T) {
	for _, word := range []string{"soft", "hard", "SOFT", " hard "} {
		normalized, known := InterruptActionWord(word)
		if !known {
			t.Fatalf("action word %q is not accepted", word)
		}
		payload, err := InterruptPayload("interrupt", normalized, "stop now")
		if err != nil {
			t.Fatalf("action word %q normalized to %q then failed: %v", word, normalized, err)
		}
		want := `{"action":"` + interruptActions[normalized] + `","message":"stop now"}`
		if string(payload) != want {
			t.Fatalf("action word %q payload=%s want=%s", word, payload, want)
		}
	}
}
