package main

import "testing"

// TestVersionRequestedIgnoresAnOptionValue guards the daemon's own option set.
//
// The daemon answers a version request before configuration is loaded, so the scan
// that detects the request runs on raw arguments. It must know which options consume
// the following argument, because "--tls-certificate-file -v" names a file called
// "-v". Passing no option set would answer a version request the operator never
// made, and the operator would see a version banner instead of the error their
// command should have produced.
//
// This is asserted through the daemon's own helper rather than through the shared
// scanner, because the defect is in what the daemon passes to the scanner. A test of
// the scanner alone passes with an empty set, which is exactly the state this guards
// against.
func TestVersionRequestedIgnoresAnOptionValue(t *testing.T) {
	if versionRequested([]string{"--tls-certificate-file", "-v"}) {
		t.Fatalf("a -v used as the value of --tls-certificate-file must not be read as a version request")
	}
	if versionRequested([]string{"--database-path", "-v"}) {
		t.Fatalf("a -v used as the value of --database-path must not be read as a version request")
	}
	if versionRequested([]string{"--auth-token", "-v"}) {
		t.Fatalf("a -v used as the value of --auth-token must not be read as a version request")
	}
}

// TestVersionRequestedAnswersTheFlag guards the other direction, so the test above
// cannot pass by rejecting every argument.
func TestVersionRequestedAnswersTheFlag(t *testing.T) {
	for _, args := range [][]string{
		{"-v"},
		{"--version"},
		{"--database-path", "/tmp/server.sqlite", "-v"},
		{"--tls-shared-certificate", "-v"},
	} {
		if !versionRequested(args) {
			t.Fatalf("versionRequested(%q) did not answer the version request", args)
		}
	}
}

// TestVersionRequestedStopsAtTheTerminator guards the boundary that keeps a
// command's own arguments intact. The daemons take no positional command, so this
// is a contract check rather than a live path: a "--" must end the scan so a future
// positional form cannot have its arguments reinterpreted as this flag.
func TestVersionRequestedStopsAtTheTerminator(t *testing.T) {
	if versionRequested([]string{"--", "-v"}) {
		t.Fatalf("a -v after -- is data and must not be read as a version request")
	}
}
