package node

import (
	"os"
	"path/filepath"
)

// isFilesystemRoot reports whether a path is the root of a filesystem.
//
// The check is written against the path itself rather than against a list of
// known roots, so it answers correctly on every platform: `/` on POSIX, `C:\` on
// Windows, and a UNC share root. A scope rooted at a filesystem root exposes
// every file on that volume, which is a blast radius nobody intends to grant.
func isFilesystemRoot(path string) bool {
	cleaned := filepath.Clean(path)
	if cleaned == string(filepath.Separator) {
		return true
	}
	// A volume root such as `C:\` has no parent distinct from itself.
	if filepath.Dir(cleaned) == cleaned {
		return true
	}
	volume := filepath.VolumeName(cleaned)
	return volume != "" && cleaned == volume+string(filepath.Separator)
}

// isMountPoint reports whether a path is a mount point, so a scope root that is
// a mount of another filesystem can be refused at startup.
//
// The check compares the device of the path with the device of its parent: a
// different device means the path is a mount point. On a platform where the
// device is not reported the function returns false, which keeps the startup
// check advisory rather than platform-dependent.
func isMountPoint(path string) bool {
	cleaned := filepath.Clean(path)
	parent := filepath.Dir(cleaned)
	if parent == cleaned {
		return false
	}

	info, err := os.Lstat(cleaned)
	if err != nil {
		return false
	}
	parentInfo, err := os.Lstat(parent)
	if err != nil {
		return false
	}

	device, ok := deviceOf(info)
	if !ok {
		return false
	}
	parentDevice, ok := deviceOf(parentInfo)
	if !ok {
		return false
	}
	return device != parentDevice
}
