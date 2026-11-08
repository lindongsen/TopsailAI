package adapter

import (
	"testing"
	"unicode/utf8"
)

// TestTruncateUTF8KeepsWholeRunes proves the shared helper never returns half a
// character. Both output routes depend on it, so a regression here would corrupt
// snapshots and follow records at the same time.
func TestTruncateUTF8KeepsWholeRunes(t *testing.T) {
	cases := []struct {
		name  string
		data  string
		limit int
		want  string
	}{
		{name: "budget inside a three byte rune backs off", data: "中中中", limit: 4, want: "中"},
		{name: "budget inside the second rune keeps the first", data: "中文abc", limit: 5, want: "中"},
		{name: "budget on a rune boundary keeps both", data: "中文abc", limit: 6, want: "中文"},
		{name: "ascii is cut at the exact budget", data: "abcdefghij", limit: 4, want: "abcd"},
		{name: "data within the budget is unchanged", data: "data", limit: 4, want: "data"},
		{name: "non positive budget yields nothing", data: "data", limit: 0, want: ""},
		{name: "negative budget yields nothing", data: "data", limit: -1, want: ""},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			got := TruncateUTF8([]byte(testCase.data), testCase.limit)
			if string(got) != testCase.want {
				t.Fatalf("got=%q want=%q", got, testCase.want)
			}
			if !utf8.ValidString(string(got)) {
				t.Fatalf("got=%q is not valid UTF-8", got)
			}
			if testCase.limit > 0 && len(got) > testCase.limit {
				t.Fatalf("length=%d exceeds the %d-byte budget", len(got), testCase.limit)
			}
		})
	}
}

// TestTruncateUTF8KeepsTheValidPrefixOfInvalidData proves the helper removes only
// the trailing bytes that do not form a complete rune, so a provider payload with
// a corrupt tail still shows the readable part instead of being discarded whole.
func TestTruncateUTF8KeepsTheValidPrefixOfInvalidData(t *testing.T) {
	got := TruncateUTF8(append([]byte("中"), 0xff, 0xfe), 4)
	if string(got) != "中" {
		t.Fatalf("got=%q want the valid prefix %q", got, "中")
	}
	if !utf8.ValidString(string(got)) {
		t.Fatalf("got=%q is not valid UTF-8", got)
	}
}

// TestTruncateUTF8StopsTrimmingAfterOneRune proves the loop is bounded: data made
// entirely of invalid bytes is shortened by at most one rune's worth of bytes and
// then returned, so a corrupt payload is never trimmed down to nothing.
func TestTruncateUTF8StopsTrimmingAfterOneRune(t *testing.T) {
	got := TruncateUTF8([]byte{0xff, 0xff, 0xff, 0xff, 0xff}, 4)
	if len(got) == 0 {
		t.Fatalf("got an empty payload, want the bytes that fit")
	}
	if len(got) > 4 {
		t.Fatalf("length=%d exceeds the 4-byte budget", len(got))
	}
}
