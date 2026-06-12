// Package lock provides distributed locking using NATS KV Store.
package lock

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	"github.com/topsailai/agent-community/pkg/logger"
)

const (
	lockKeyFormat   = "acs_lock_%s_%s"
	lockTTL         = 7200 * time.Second
	renewalInterval = 10 * time.Second
)

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
		return fmt.Errorf("failed to create kv bucket: %w", err)
	}

	return nil
}

// Acquire attempts to acquire a distributed lock for the given resource.
// Returns the Lock if successful, or nil if the lock is already held.
func (dl *DistributedLock) Acquire(ctx context.Context, lockType, resourceID string) (*Lock, error) {
	kv, err := dl.js.KeyValue(dl.bucketName)
	if err != nil {
		return nil, fmt.Errorf("failed to get kv bucket: %w", err)
	}

	key := fmt.Sprintf(lockKeyFormat, lockType, resourceID)
	token := uuid.New().String()

	_, err = kv.Create(key, []byte(token))
	if err != nil {
		if err == nats.ErrKeyExists {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to create lock: %w", err)
	}

	lockCtx, cancel := context.WithCancel(ctx)
	lock := &Lock{
		lockType:     lockType,
		resourceID:   resourceID,
		fencingToken: token,
		kv:           kv,
		cancel:       cancel,
	}

	go lock.renew(lockCtx, key, token)

	logger.Info("lock acquired", "lock", lockType, "resource", resourceID, "token", token)

	return lock, nil
}

// renew periodically renews the lock via Update until the context is cancelled.
func (l *Lock) renew(ctx context.Context, key, token string) {
	ticker := time.NewTicker(renewalInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			entry, err := l.kv.Get(key)
			if err != nil {
				logger.Error("failed to get lock entry for renewal", "key", key, "error", err)
				continue
			}

			if string(entry.Value()) != token {
				logger.Warn("lock token mismatch during renewal, stopping renewal", "key", key)
				return
			}

			_, err = l.kv.Update(key, []byte(token), entry.Revision())
			if err != nil {
				logger.Error("failed to renew lock", "key", key, "error", err)
			}
		}
	}
}

// Release releases the distributed lock.
func (l *Lock) Release() error {
	l.cancel()

	key := fmt.Sprintf(lockKeyFormat, l.lockType, l.resourceID)

	entry, err := l.kv.Get(key)
	if err != nil {
		if err == nats.ErrKeyNotFound {
			return nil
		}
		return fmt.Errorf("failed to get lock entry for release: %w", err)
	}

	if string(entry.Value()) != l.fencingToken {
		return fmt.Errorf("fencing token mismatch: cannot release lock held by another owner")
	}

	if err := l.kv.Delete(key); err != nil {
		return fmt.Errorf("failed to delete lock: %w", err)
	}

	logger.Info("lock released", "lock", l.lockType, "resource", l.resourceID)

	return nil
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
