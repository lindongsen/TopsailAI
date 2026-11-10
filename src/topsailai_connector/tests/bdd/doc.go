// Package bdd runs the Gherkin scenarios in features/ against the Node library.
//
// The suite is behind the `bdd` build tag so `go test ./...` stays a unit run.
// It needs no built binary, because every scenario drives a library call rather
// than a process.
//
// The runner is deliberately small: it reads a feature file, matches each step
// against a registered regular expression and reports the scenario that failed.
// A third-party Gherkin library would add a dependency to a project whose only
// dependency is a YAML parser, and the subset used here is a few hundred lines.
package bdd
