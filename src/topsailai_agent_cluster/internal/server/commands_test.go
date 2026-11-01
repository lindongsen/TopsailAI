package server

import "testing"

func TestParseCommandLimitBoundaries(t *testing.T) {
	cases := []struct {
		input string
		want  int
	}{{"", 20}, {"bad", 20}, {"0", 20}, {"-1", 20}, {"20", 20}, {"101", 100}}
	for _, tc := range cases {
		if got := parseCommandLimit(tc.input); got != tc.want {
			t.Errorf("parseCommandLimit(%q)=%d want %d", tc.input, got, tc.want)
		}
	}
}
