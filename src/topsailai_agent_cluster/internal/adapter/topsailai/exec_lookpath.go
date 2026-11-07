package topsailai

import "os/exec"

// lookPath resolves a program name through PATH.
//
// It is a package-level variable so a test can substitute a resolver without
// depending on which programs the test host happens to have installed.
var lookPath = exec.LookPath
