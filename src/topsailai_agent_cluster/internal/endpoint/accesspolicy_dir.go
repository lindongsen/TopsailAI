package endpoint

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
)

// AccessPolicyDir loads the Endpoint access policy from a directory of policy
// files and reloads it on demand.
//
// The directory is the unit of configuration, not the file, because the policy
// has to be read as one set: a token is identified by whichever file declares it,
// and two files declaring the same token are a conflict rather than a merge. A
// per-file loader could not detect that conflict, so the directory is loaded as a
// whole and swapped as a whole.
//
// Reload is explicit rather than periodic, following the command allowlist: a
// signal or an administrative call triggers it, so the policy in force never
// drifts silently from the files on disk and a busy Endpoint does not stat the
// directory for every request.
type AccessPolicyDir struct {
	// Path is the configured directory. An empty path means the policy was never
	// configured, which is the permissive state.
	Path string
	// Policy is the policy currently in force.
	Policy *AccessPolicy
}

// LoadAccessPolicyDir reads and validates every policy file in dir.
//
// Three outcomes are deliberate:
//
//   - An empty path, or a path that does not exist, yields a permissive policy.
//     This is the upgrade-safe default: an Endpoint that refused every caller
//     until an operator created a directory would break every existing
//     deployment the moment the feature shipped.
//   - A directory with no policy file yields a permissive policy, so creating the
//     directory is not itself a policy change. An operator can stage the
//     directory before writing the first file.
//   - A directory with at least one policy file yields a restricted policy, and a
//     token with no matching file is refused. The alternative, allowing an
//     unlisted token, would mean that adding one file left every other caller at
//     full authority, which is the opposite of what an operator writing a policy
//     intends.
func LoadAccessPolicyDir(dir string) (*AccessPolicyDir, error) {
	if dir == "" {
		return &AccessPolicyDir{Policy: NewPermissiveAccessPolicy()}, nil
	}
	policy, err := loadAccessPolicyFromDir(dir)
	if err != nil {
		return nil, err
	}
	return &AccessPolicyDir{Path: dir, Policy: policy}, nil
}

// Reload re-reads the directory and swaps the policy atomically. A read or parse
// failure keeps the previous policy in force and returns the error, so a broken
// edit cannot disable or widen the policy.
func (d *AccessPolicyDir) Reload() error {
	if d.Path == "" {
		return nil
	}
	next, err := loadAccessPolicyFromDir(d.Path)
	if err != nil {
		return err
	}
	d.Policy.replace(next)
	return nil
}

// WatchReload reloads the policy on SIGHUP until the returned stop function is
// called or the context is cancelled.
//
// SIGHUP is registered explicitly because Go terminates a process on SIGHUP by
// default, so without this handler the reload signal would kill the Endpoint.
// Several components may watch SIGHUP at once; each registers its own channel and
// the runtime delivers the signal to all of them, so one reload signal refreshes
// every file-backed policy together.
func (d *AccessPolicyDir) WatchReload(ctx context.Context, onReload func(error)) (func(), error) {
	watchCtx, cancel := context.WithCancel(ctx)
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGHUP)
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			select {
			case <-watchCtx.Done():
				return
			case <-signals:
				if onReload != nil {
					onReload(d.Reload())
				}
			}
		}
	}()
	var once sync.Once
	stop := func() {
		once.Do(func() {
			signal.Stop(signals)
			cancel()
			<-done
		})
	}
	return stop, nil
}

// loadAccessPolicyFromDir reads every policy file in dir and builds one policy.
//
// The whole directory is parsed before anything is returned, so a single broken
// file fails the load instead of leaving a partially applied policy behind. That
// is the fail-closed direction: an operator who mistyped one file learns about it
// rather than silently running with the other files only.
func loadAccessPolicyFromDir(dir string) (*AccessPolicy, error) {
	info, err := os.Stat(dir)
	if err != nil {
		if os.IsNotExist(err) {
			// A missing directory is the permissive state, not an error. An
			// operator who never configured a policy must not be forced to
			// create one to keep the Endpoint working.
			return NewPermissiveAccessPolicy(), nil
		}
		return nil, fmt.Errorf("stat access policy directory %q: %w", dir, err)
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("access policy path %q is not a directory", dir)
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("read access policy directory %q: %w", dir, err)
	}
	names := make([]string, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		if !strings.HasSuffix(entry.Name(), accessPolicyFileSuffix) {
			continue
		}
		names = append(names, entry.Name())
	}
	// Sort so the load order is deterministic. The order does not change the
	// effective policy, because a duplicate token is rejected rather than
	// resolved, but a stable order makes the reported conflict reproducible.
	sort.Strings(names)
	rules := make([]AccessRule, 0, len(names))
	byIdentity := make(map[string]string, len(names))
	for _, name := range names {
		path := filepath.Join(dir, name)
		data, err := os.ReadFile(path)
		if err != nil {
			return nil, fmt.Errorf("read access policy file %q: %w", path, err)
		}
		rule, _, err := ParseAccessRule(data, path)
		if err != nil {
			return nil, err
		}
		identity := rule.identity()
		if previous, ok := byIdentity[identity]; ok {
			return nil, fmt.Errorf("access policy files %q and %q declare the same token", previous, path)
		}
		byIdentity[identity] = path
		rules = append(rules, rule)
	}
	return NewAccessPolicy(rules), nil
}
