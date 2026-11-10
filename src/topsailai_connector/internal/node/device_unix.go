//go:build unix

package node

import (
	"os"
	"syscall"
)

// deviceOf reports the device a file lives on, so a mount point can be
// recognised by comparing a path with its parent.
func deviceOf(info os.FileInfo) (uint64, bool) {
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return 0, false
	}
	return uint64(stat.Dev), true
}
