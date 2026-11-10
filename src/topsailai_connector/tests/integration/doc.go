// Package integration runs the real connector binaries as child processes.
//
// The suite is behind the `integration` build tag so `go test ./...` stays a
// unit run: an integration test needs a built binary and a writable temporary
// directory, and a unit run must not depend on either.
//
// Every test here starts a process, observes what it prints, and stops it by
// signal. Nothing is asserted about internal state, because the point of this
// layer is that the process boundary behaves as documented.
package integration
