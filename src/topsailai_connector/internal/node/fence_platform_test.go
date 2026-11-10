//go:build unix

package node

import (
	"path/filepath"
	"syscall"
	"testing"

	"topsailai_connector/internal/protocol"
)

// TestScopeReadRejectsFifo checks that a named pipe is refused rather than
// read.
//
// A fifo blocks forever when opened for reading with no writer, so reading one
// would turn a single request into a hang: a denial of service with no exploit
// beyond the path itself. This test is the reason the open is non-blocking: a
// blocking open never reaches the type check that refuses the fifo.
func TestScopeReadRejectsFifo(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	if err := syscall.Mkfifo(filepath.Join(root, "pipe"), 0o644); err != nil {
		t.Skipf("mkfifo unsupported here: %v", err)
	}

	_, _, err := scope.Read("pipe", 0, 0)
	if err == nil {
		t.Fatal("Read(fifo) = nil error, want a refusal")
	}
	if code := CodeOf(err); code != protocol.CodeInvalidArgument {
		t.Fatalf("Read(fifo) code = %s, want invalid_argument", code.Name())
	}
}

// TestScopeStatReportsFifo checks that a fifo is statable and named as a fifo,
// so a caller can see what it is without opening it.
func TestScopeStatReportsFifo(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	if err := syscall.Mkfifo(filepath.Join(root, "pipe"), 0o644); err != nil {
		t.Skipf("mkfifo unsupported here: %v", err)
	}

	entry, err := scope.Stat("pipe")
	if err != nil {
		t.Fatalf("Stat(fifo) = %v, want nil", err)
	}
	if entry.Type != "fifo" {
		t.Fatalf("Stat(fifo) type = %q, want fifo", entry.Type)
	}
}

// TestScopeReadRejectsDeviceFile checks that a device file is refused rather
// than read. A device such as /dev/zero never ends, so reading one would turn a
// single request into an unbounded allocation.
func TestScopeReadRejectsDeviceFile(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	// A symlink to a device is refused by the fence before the type check, so
	// the device must be created inside the scope to reach the type check.
	devicePath := filepath.Join(root, "zero")
	if err := syscall.Mknod(devicePath, syscall.S_IFCHR|0o644, int(mkdev(1, 5))); err != nil {
		t.Skipf("mknod requires privilege here: %v", err)
	}

	_, _, err := scope.Read("zero", 0, 0)
	if err == nil {
		t.Fatal("Read(device) = nil error, want a refusal")
	}
	if code := CodeOf(err); code != protocol.CodeInvalidArgument {
		t.Fatalf("Read(device) code = %s, want invalid_argument", code.Name())
	}
}

// mkdev builds a device number the way the kernel expects it, so the test does
// not depend on a platform-specific helper.
func mkdev(major uint32, minor uint32) uint64 {
	return uint64(major)<<8 | uint64(minor)
}
