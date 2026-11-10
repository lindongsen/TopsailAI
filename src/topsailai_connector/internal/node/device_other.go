//go:build !unix

package node

import "os"

// deviceOf reports that the device of a file is not available on this platform.
// The mount-point check therefore reports false, which keeps the startup rule
// advisory instead of refusing a legitimate scope on a platform where the
// comparison cannot be made.
func deviceOf(info os.FileInfo) (uint64, bool) {
	return 0, false
}
