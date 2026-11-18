//go:build linux

package main

import (
	"os"
	"syscall"
)

// sysPidfdOpen is the pidfd_open syscall number.
//
// The standard library declares this number only for loong64, and this module
// carries no dependency beyond the tokenizer, so the value is declared here. It is
// 434 on every architecture that implements the call.
const sysPidfdOpen = 434

// platformCapabilities reports the host support agent.stop requires.
//
// Stopping a provider process needs a readable process table, because the identity
// of the target must be verified before a signal is delivered. A pidfd is recorded
// as evidence of the stronger binding, but it is not a requirement: when the pidfd
// bindings are unavailable the provider CLI re-verifies the process identity
// immediately before signalling, so the operation is still reachable.
//
// The gate therefore describes reachability, not the strongest available guarantee.
// A capability claim must reflect whether the operation can be performed at all, not
// whether it can be performed in the best way. Requiring the stronger binding here
// would hide an operation that works, and the operator would lose a capability the
// deployment can actually serve.
type platformCapabilities struct {
	ProcAvailable  bool
	PidfdAvailable bool
}

// stopSupported reports whether this host can stop a provider process.
//
// Only the process table is required. PidfdAvailable is not a precondition, because
// the provider CLI falls back to an identity recheck when the pidfd bindings are
// absent. The binding actually used is reported per invocation in the receipt, so
// this field stays probe evidence and is never a second source of truth for it.
func (c platformCapabilities) stopSupported() bool {
	return c.ProcAvailable
}

// pidfdAvailable reports whether one syscall number opens a pidfd for this process.
//
// The number is a parameter rather than a constant read, so a test can pass a number
// that cannot work and observe the failure. A probe that ignored its input would
// report support on every host, which is exactly the assumption the gate exists to
// remove.
func pidfdAvailable(syscallNumber uintptr) bool {
	fd, _, errno := syscall.Syscall(syscallNumber, uintptr(os.Getpid()), 0, 0)
	if errno != 0 {
		return false
	}
	return syscall.Close(int(fd)) == nil
}

// probePlatformCapabilities detects host support once at startup.
//
// The probe opens a pidfd for this very process and closes it again, so it proves
// the call works without touching any other process.
func probePlatformCapabilities() platformCapabilities {
	if _, err := os.Stat("/proc"); err != nil {
		return platformCapabilities{}
	}
	return platformCapabilities{ProcAvailable: true, PidfdAvailable: pidfdAvailable(sysPidfdOpen)}
}
