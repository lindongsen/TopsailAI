// Package lock provides distributed locking using NATS KV Store.
package lock

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	"github.com/topsailai/agent-community/pkg/logger"
)

const (
	lockKeyFormat   = "acs.lock.%s.%s"
	lockTTL         = 7200 * time.Second
	renewalInterval = 10 * time.Second
)

// ErrLockHeld is returned by Acquire when the lock is already held by another owner.
var ErrLockHeld = errors.New("lock is already held")

// DistributedLock provides distributed locking via NATS KV.
type DistributedLock struct {
	js         nats.JetStreamContext
	bucketName string
}

// Lock represents a held distributed lock.
type Lock struct {
	lockType     string
	resourceID   string
	fencingToken string
	kv           nats.KeyValue
	cancel       context.CancelFunc
	releaseOnce  sync.Once
	renewWg      sync.WaitGroup
	lostOnce     sync.Once
	lostCh       chan struct{}
}

// NewDistributedLock creates a new distributed lock manager.
func NewDistributedLock(js nats.JetStreamContext, bucketName string) (*DistributedLock, error) {
	dl := &DistributedLock{
		js:         js,
		bucketName: bucketName,
	}

	if err := dl.ensureBucket(); err != nil {
		return nil, fmt.Errorf("failed to ensure lock bucket: %w", err)
	}

	return dl, nil
}

// ensureBucket creates the KV bucket if it does not exist.
func (dl *DistributedLock) ensureBucket() error {
	_, err := dl.js.KeyValue(dl.bucketName)
	if err == nil {
		return nil
	}
	if err != nats.ErrBucketNotFound {
		return fmt.Errorf("failed to check kv bucket: %w", err)
	}

	_, err = dl.js.CreateKeyValue(&nats.KeyValueConfig{
		Bucket: dl.bucketName,
		TTL:    lockTTL,
	})
	if err != nil {
		// Another instance may have created the bucket concurrently.
		if err == nats.ErrBucketExists {
			return nil
		}
		return fmt.Errorf("failed to create kv bucket: %w", err)
	}

	return nil
}

// validateLockKeyPart ensures the lock type or resource ID does not contain the
// key separator '.', which would produce ambiguous lock keys.
func validateLockKeyPart(name, value string) error {
	if strings.TrimSpace(value) == "" {
		return fmt.Errorf("%s must not be empty", name)
	}
	if strings.Contains(value, ".") {
		return fmt.Errorf("%s must not contain '.'", name)
	}
	return nil
}

// Acquire attempts to acquire a distributed lock for the given resource.
// Returns the Lock if successful, or ErrLockHeld if the lock is already held.
func (dl *DistributedLock) Acquire(ctx context.Context, lockType, resourceID string) (*Lock, error) {
	if err := validateLockKeyPart("lockType", lockType); err != nil {
		return nil, fmt.Errorf("invalid lock type: %w", err)
	}
	if err := validateLockKeyPart("resourceID", resourceID); err != nil {
		return nil, fmt.Errorf("invalid resource id: %w", err)
	}

	kv, err := dl.js.KeyValue(dl.bucketName)
	if err != nil {
		return nil, fmt.Errorf("failed to get kv bucket: %w", err)
	}

	key := fmt.Sprintf(lockKeyFormat, lockType, resourceID)
	token := uuid.New().String()

	createRevision, err := kv.Create(key, []byte(token))
	if err != nil {
		if err == nats.ErrKeyExists {
			return nil, ErrLockHeld
		}
		return nil, fmt.Errorf("failed to create lock: %w", err)
	}

	// Use an independent background context for renewal so that cancellation of
	// the caller's context does not stop the lock from being kept alive. The lock
	// is released only when Release() is called.
	lockCtx, cancel := context.WithCancel(context.Background())
	lock := &Lock{
		lockType:     lockType,
		resourceID:   resourceID,
		fencingToken: token,
		kv:           kv,
		cancel:       cancel,
		lostCh:       make(chan struct{}),
	}

	lock.renewWg.Add(1)
	go lock.renew(lockCtx, key, token)

	logger.Info("lock acquired", "lock", lockType, "resource", resourceID, "token", token, "key", key, "revision", createRevision)

	return lock, nil
}

// renew periodically renews the lock via Update until the context is cancelled.
func (l *Lock) renew(ctx context.Context, key, token string) {
	defer l.renewWg.Done()

	ticker := time.NewTicker(renewalInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			entry, err := l.kv.Get(key)
			if err != nil {
				if err == nats.ErrKeyNotFound {
					logger.Warn("lock key disappeared during renewal", "key", key, "token", token)
					l.markLost()
					return
				}
				logger.Error("failed to get lock entry for renewal", "key", key, "error", err)
				continue
			}

			actual := string(entry.Value())
			if actual != token {
				logger.Warn("lock token mismatch during renewal, stopping renewal", "key", key, "expected", token, "actual", actual, "revision", entry.Revision())
				l.markLost()
				return
			}

			newRevision, err := l.kv.Update(key, []byte(token), entry.Revision())
			if err != nil {
				if errors.Is(err, nats.ErrKeyNotFound) {
					logger.Warn("lock key not found during renewal update", "key", key, "token", token)
					l.markLost()
					return
				}
				if errors.Is(err, nats.ErrKeyMismatch) {
					logger.Warn("lock revision mismatch during renewal, lock was modified by another owner", "key", key, "token", token)
					l.markLost()
					return
				}
				logger.Error("failed to renew lock", "key", key, "error", err, "revision", entry.Revision())
				continue
			}

			logger.Debug("lock renewed", "key", key, "token", token, "old_revision", entry.Revision(), "new_revision", newRevision)
		}
	}
}

// markLost signals that this lock instance is no longer valid. It is safe to
// call multiple times.
func (l *Lock) markLost() {
	l.lostOnce.Do(func() {
		close(l.lostCh)
	})
}

// Lost returns a channel that is closed when the lock is detected to be no
// longer held (for example, due to token mismatch, revision mismatch, or the
// key disappearing). Callers can use this to abort guarded work when the lock
// is lost.
func (l *Lock) Lost() <-chan struct{} {
	return l.lostCh
}

// IsHeld returns true if the lock has not been observed as lost. It performs a
// live check against NATS KV and returns false if the key is missing or the
// fencing token no longer matches.
func (l *Lock) IsHeld() (bool, error) {
	select {
	case <-l.lostCh:
		return false, nil
	default:
	}

	key := fmt.Sprintf(lockKeyFormat, l.lockType, l.resourceID)
	entry, err := l.kv.Get(key)
	if err != nil {
		if err == nats.ErrKeyNotFound {
			l.markLost()
			return false, nil
		}
		return false, fmt.Errorf("failed to get lock entry: %w", err)
	}

	if string(entry.Value()) != l.fencingToken {
		l.markLost()
		return false, nil
	}

	return true, nil
}

// Release releases the distributed lock. It is safe to call multiple times.
func (l *Lock) Release() error {
	var releaseErr error
	l.releaseOnce.Do(func() {
		l.cancel()
		l.renewWg.Wait()

		key := fmt.Sprintf(lockKeyFormat, l.lockType, l.resourceID)

		entry, err := l.kv.Get(key)
		if err != nil {
			if err == nats.ErrKeyNotFound {
				logger.Info("lock release: key not found", "key", key)
				return
			}
			releaseErr = fmt.Errorf("failed to get lock entry for release: %w", err)
			return
		}

		actual := string(entry.Value())
		if actual != l.fencingToken {
			releaseErr = fmt.Errorf("fencing token mismatch: cannot release lock held by another owner (expected=%q, actual=%q, revision=%d)", l.fencingToken, actual, entry.Revision())
			return
		}

		if err := l.kv.Delete(key); err != nil {
			releaseErr = fmt.Errorf("failed to delete lock: %w", err)
			return
		}

		logger.Info("lock released", "lock", l.lockType, "resource", l.resourceID, "token", l.fencingToken, "revision", entry.Revision())
	})

	return releaseErr
}

// FencingToken returns the fencing token for this lock.
func (l *Lock) FencingToken() string {
	return l.fencingToken
}

// LockType returns the lock type.
func (l *Lock) LockType() string {
	return l.lockType
}

// ResourceID returns the resource ID.
func (l *Lock) ResourceID() string {
	return l.resourceID
}
