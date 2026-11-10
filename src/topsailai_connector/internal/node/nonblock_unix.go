//go:build unix

package node

import "syscall"

// nonBlockFlag makes an open return immediately instead of waiting for a fifo
// writer. Without it, opening a fifo for reading blocks inside open(2) and the
// type check that refuses the fifo is never reached.
const nonBlockFlag = syscall.O_NONBLOCK
