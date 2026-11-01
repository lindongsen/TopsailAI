//go:build linux

package topsailai

import (
	"errors"
	"os"
	"runtime"

	"golang.org/x/sys/unix"
)

func defaultPlatformProbe() (PlatformCapabilities, error) {
	if runtime.GOOS != "linux" {
		return PlatformCapabilities{}, nil
	}
	if _, err := os.Stat("/proc"); err != nil {
		return PlatformCapabilities{}, err
	}
	pidfd, err := unix.PidfdOpen(os.Getpid(), 0)
	if err != nil {
		return PlatformCapabilities{}, err
	}
	if err := unix.Close(pidfd); err != nil {
		return PlatformCapabilities{}, errors.New("close pidfd probe: " + err.Error())
	}
	return PlatformCapabilities{ProcAvailable: true, PidfdAvailable: true}, nil
}
