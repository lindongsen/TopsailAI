package tui

import (
	"context"
	"errors"
	"io"
	"strings"
	"sync"
	"testing"
	"time"
)

// unitCBlockingReadCloser makes ownership and release observable without sleeps.
type unitCBlockingReadCloser struct {
	entered chan struct{}
	release chan struct{}
	closed  chan struct{}
	once    sync.Once
	closes  int
	mu      sync.Mutex
}

func newUnitCBlockingReadCloser() *unitCBlockingReadCloser {
	return &unitCBlockingReadCloser{entered: make(chan struct{}), release: make(chan struct{}), closed: make(chan struct{})}
}

func (r *unitCBlockingReadCloser) Read([]byte) (int, error) {
	r.once.Do(func() { close(r.entered) })
	select {
	case <-r.release:
		return 0, io.EOF
	case <-r.closed:
		return 0, io.ErrClosedPipe
	}
}

func (r *unitCBlockingReadCloser) Close() error {
	r.mu.Lock()
	r.closes++
	r.mu.Unlock()
	select {
	case <-r.closed:
	default:
		close(r.closed)
	}
	return nil
}

func (r *unitCBlockingReadCloser) closeCount() int { r.mu.Lock(); defer r.mu.Unlock(); return r.closes }

func TestUnitCStartOwnedReaderWatcherConvergence(t *testing.T) {
	parent, cancel := context.WithCancel(context.Background())
	reader := newUnitCBlockingReadCloser()
	result := make(chan error, 1)
	go func() {
		result <- RunInteractive(parent, newUnitCAPI(), reader, io.Discard, io.Discard, InteractiveOptions{CloseInput: true})
	}()
	select {
	case <-reader.entered:
	case <-time.After(time.Second):
		t.Fatal("reader did not enter")
	}
	cancel()
	select {
	case err := <-result:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("error=%v, want context.Canceled", err)
		}
	case <-time.After(time.Second):
		t.Fatal("owned reader did not converge")
	}
	if reader.closeCount() == 0 {
		t.Fatal("owned reader was not closed")
	}
}

func TestUnitCStartInputOwnershipMatrix(t *testing.T) {
	cases := []struct {
		name       string
		closeInput bool
	}{
		{"owned", true}, {"caller-owned", false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			parent, cancel := context.WithCancel(context.Background())
			reader := newUnitCBlockingReadCloser()
			result := make(chan error, 1)
			go func() {
				result <- RunInteractive(parent, newUnitCAPI(), reader, io.Discard, io.Discard, InteractiveOptions{CloseInput: tc.closeInput})
			}()
			select {
			case <-reader.entered:
			case <-time.After(time.Second):
				t.Fatal("reader did not enter")
			}
			cancel()
			if tc.closeInput {
				select {
				case err := <-result:
					if !errors.Is(err, context.Canceled) {
						t.Fatalf("error=%v", err)
					}
				case <-time.After(time.Second):
					t.Fatal("owned input did not stop")
				}
				if reader.closeCount() == 0 {
					t.Fatal("owned reader was not closed")
				}
				return
			}
			select {
			case err := <-result:
				t.Fatalf("caller-owned reader returned before release: %v", err)
			default:
			}
			close(reader.release)
			select {
			case err := <-result:
				if !errors.Is(err, context.Canceled) {
					t.Fatalf("error=%v", err)
				}
			case <-time.After(time.Second):
				t.Fatal("caller-owned input did not join")
			}
			if reader.closeCount() != 0 {
				t.Fatalf("caller-owned reader was closed %d times", reader.closeCount())
			}
		})
	}
}

func TestUnitCStartStdinOwnershipChild(t *testing.T) {
	reader := strings.NewReader("quit\n")
	if err := RunInteractive(context.Background(), newUnitCAPI(), reader, io.Discard, io.Discard, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
}
