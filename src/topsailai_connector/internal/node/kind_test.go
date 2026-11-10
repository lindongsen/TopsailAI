package node

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// fakeFileInfo is an os.FileInfo with a chosen mode and an optional Sys value.
//
// It exists so the type and device helpers can be exercised for file kinds a
// test cannot create portably: a socket needs a listener, and a device file needs
// privileges. A helper that is only ever called with a regular file is a helper
// whose other branches nobody has run.
type fakeFileInfo struct {
	name string
	mode os.FileMode
	sys  any
}

func (f fakeFileInfo) Name() string       { return f.name }
func (f fakeFileInfo) Size() int64        { return 0 }
func (f fakeFileInfo) Mode() os.FileMode  { return f.mode }
func (f fakeFileInfo) ModTime() time.Time { return time.Unix(0, 0).UTC() }
func (f fakeFileInfo) IsDir() bool        { return f.mode.IsDir() }
func (f fakeFileInfo) Sys() any           { return f.sys }

// TestTypeOfNamesKindsARealFileCannotCreate checks the file kinds a test cannot
// create portably: a socket needs a listener and a device file needs privileges.
// A helper that is only ever called with a regular file is a helper whose other
// branches nobody has run.
func TestTypeOfNamesKindsARealFileCannotCreate(t *testing.T) {
	cases := []struct {
		name string
		mode os.FileMode
		want string
	}{
		{"regular", 0o644, "file"},
		{"directory", os.ModeDir | 0o755, "dir"},
		{"symlink", os.ModeSymlink | 0o777, "symlink"},
		{"fifo", os.ModeNamedPipe | 0o644, "fifo"},
		{"socket", os.ModeSocket | 0o644, "socket"},
		{"device", os.ModeDevice | 0o644, "device"},
		{"char device", os.ModeDevice | os.ModeCharDevice | 0o644, "device"},
		{"irregular", os.ModeIrregular | 0o644, "unknown"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			got := typeOf(fakeFileInfo{name: testCase.name, mode: testCase.mode})
			if got != testCase.want {
				t.Fatalf("typeOf(%v) = %q, want %q", testCase.mode, got, testCase.want)
			}
		})
	}
}

// TestDeviceOfReportsNoDeviceForAnUnknownSys checks that a FileInfo whose Sys
// value is not a stat structure reports no device, so the mount-point check
// degrades to "not a mount point" instead of comparing two zero devices.
func TestDeviceOfReportsNoDeviceForAnUnknownSys(t *testing.T) {
	if _, ok := deviceOf(fakeFileInfo{name: "fake", mode: 0o644, sys: "not a stat"}); ok {
		t.Fatal("deviceOf(fake) reported a device, want none")
	}
}

// TestDeviceOfReportsADeviceForARealFile checks that a real file reports a
// device, so the mount-point check has something to compare.
func TestDeviceOfReportsADeviceForARealFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "file")
	writeFile(t, path, "content")

	info, err := os.Lstat(path)
	if err != nil {
		t.Fatalf("lstat: %v", err)
	}
	if _, ok := deviceOf(info); !ok {
		t.Fatal("deviceOf(real file) reported no device, want one")
	}
}

// TestCheckIdentityFileModeReportsAMissingFile checks that a missing identity
// file is reported rather than treated as acceptable, because the mode check must
// not pass by being unable to look.
func TestCheckIdentityFileModeReportsAMissingFile(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "absent")
	if err := checkIdentityFileMode(missing); err == nil {
		t.Fatal("checkIdentityFileMode(missing) = nil error, want a failure")
	}
}
