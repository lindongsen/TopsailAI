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
// Stopping a provider process safely needs two facts: the process table is
// readable, and a pidfd can be opened so the signal cannot be delivered to a
// recycled process identity. A host that cannot prove both is reported as
// unsupported rather than assumed to work.
type platformCapabilities struct {
	ProcAvailable  bool
	PidfdAvailable bool
}

// stopSupported reports whether this host can stop a provider process safely.
func (c platformCapabilities) stopSupported() bool {
	return c.ProcAvailable && c.PidfdAvailable
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
