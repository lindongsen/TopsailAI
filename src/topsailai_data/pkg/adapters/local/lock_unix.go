//go:build unix

package local

import (
	"os"

	"github.com/topsailai/topsailai_data/pkg/errors"
	"golang.org/x/sys/unix"
)

// flockAcquire attempts to acquire a non-blocking advisory lock on f.
// exclusive selects LOCK_EX; otherwise LOCK_SH is used.
func flockAcquire(f *os.File, exclusive bool) error {
	flag := unix.LOCK_SH | unix.LOCK_NB
	if exclusive {
		flag = unix.LOCK_EX | unix.LOCK_NB
	}
	for {
		err := unix.Flock(int(f.Fd()), flag)
		if err == nil {
			return nil
		}
		if err == unix.EINTR {
			continue
		}
		if err == unix.EWOULDBLOCK || err == unix.EAGAIN {
			return errors.ErrObjectLocked
		}
		return err
	}
}

// flockRelease releases the advisory lock held on f.
func flockRelease(f *os.File) error {
	for {
		err := unix.Flock(int(f.Fd()), unix.LOCK_UN)
		if err == nil {
			return nil
		}
		if err != unix.EINTR {
			return err
		}
	}
}
