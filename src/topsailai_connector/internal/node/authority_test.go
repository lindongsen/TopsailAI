package node

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"topsailai_connector/internal/node/policy"
	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// authorityFixture is a policy file plus the directories it names.
type authorityFixture struct {
	base       string
	policyPath string
	project    string
	scratch    string
}

// newAuthorityFixture builds two scope directories and a policy file that
// defines both, so a multi-scope startup has something real to open.
func newAuthorityFixture(t *testing.T) *authorityFixture {
	t.Helper()

	base := t.TempDir()
	project := filepath.Join(base, "project")
	scratch := filepath.Join(base, "scratch")
	for _, directory := range []string{project, scratch} {
		if err := os.Mkdir(directory, 0o755); err != nil {
			t.Fatalf("mkdir %q: %v", directory, err)
		}
	}
	writeFile(t, filepath.Join(project, "inside.txt"), "inside content")

	policyPath := filepath.Join(base, "policy.yaml")
	writeFile(t, policyPath, "version: 1\n"+
		"scopes:\n"+
		"  project:\n"+
		"    path: "+project+"\n"+
		"  scratch:\n"+
		"    path: "+scratch+"\n"+
		"grants:\n"+
		"  - scope: project\n"+
		"    permissions: [read, list, stat]\n"+
		"  - scope: scratch\n"+
		"    permissions: [list]\n")

	return &authorityFixture{
		base:       base,
		policyPath: policyPath,
		project:    project,
		scratch:    scratch,
	}
}

// load opens the fixture's authority and registers its cleanup.
func (f *authorityFixture) load(t *testing.T, denyPaths []string) *Authority {
	t.Helper()
	authority, err := LoadAuthority(f.policyPath, denyPaths, "")
	if err != nil {
		t.Fatalf("LoadAuthority() = %v, want nil", err)
	}
	t.Cleanup(func() { authority.Close() })
	return authority
}

// TestLoadAuthorityOpensEveryScope checks that a policy defining two scopes
// yields two open scopes, because a Node that silently serves a subset of its
// policy is a Node whose operator believes a grant exists that does not.
func TestLoadAuthorityOpensEveryScope(t *testing.T) {
	fixture := newAuthorityFixture(t)
	authority := fixture.load(t, nil)

	names := authority.ScopeNames()
	if len(names) != 2 {
		t.Fatalf("ScopeNames() = %v, want 2 names", names)
	}
	if names[0] != security.Scope("project") || names[1] != security.Scope("scratch") {
		t.Fatalf("ScopeNames() = %v, want [project scratch] in sorted order", names)
	}

	for _, name := range names {
		scope, ok := authority.Scope(name)
		if !ok {
			t.Fatalf("Scope(%q) reported missing, want present", name)
		}
		if scope == nil {
			t.Fatalf("Scope(%q) = nil, want an open scope", name)
		}
	}
}

// TestLoadAuthorityResolvesScopePaths checks that each scope resolved to the
// directory the policy named, so a mapping mistake is caught at startup rather
// than at the first request.
func TestLoadAuthorityResolvesScopePaths(t *testing.T) {
	fixture := newAuthorityFixture(t)
	authority := fixture.load(t, nil)

	project, ok := authority.Scope(security.Scope("project"))
	if !ok {
		t.Fatal("Scope(project) reported missing, want present")
	}
	if project.ResolvedPath() != fixture.project {
		t.Fatalf("ResolvedPath() = %q, want %q", project.ResolvedPath(), fixture.project)
	}

	scratch, ok := authority.Scope(security.Scope("scratch"))
	if !ok {
		t.Fatal("Scope(scratch) reported missing, want present")
	}
	if scratch.ResolvedPath() != fixture.scratch {
		t.Fatalf("ResolvedPath() = %q, want %q", scratch.ResolvedPath(), fixture.scratch)
	}
}

// TestLoadAuthorityRejectsMissingPolicyFile checks that a missing policy file
// fails startup instead of being read as an empty policy, because an empty policy
// refuses everything and looks like a working Node.
func TestLoadAuthorityRejectsMissingPolicyFile(t *testing.T) {
	base := t.TempDir()
	missing := filepath.Join(base, "absent.yaml")

	authority, err := LoadAuthority(missing, nil, "")
	if err == nil {
		authority.Close()
		t.Fatal("LoadAuthority() = nil error, want a failure for a missing file")
	}
	if !errors.Is(err, policy.ErrMissingFile) {
		t.Fatalf("LoadAuthority() error = %v, want it to wrap ErrMissingFile", err)
	}
}

// TestLoadAuthorityRejectsInvalidYAML checks that a malformed policy fails
// startup, because a policy nobody can parse is a policy nobody can reason about.
func TestLoadAuthorityRejectsInvalidYAML(t *testing.T) {
	base := t.TempDir()
	policyPath := filepath.Join(base, "policy.yaml")
	writeFile(t, policyPath, "version: 1\nscopes: [this is not a mapping\n")

	authority, err := LoadAuthority(policyPath, nil, "")
	if err == nil {
		authority.Close()
		t.Fatal("LoadAuthority() = nil error, want a failure for malformed YAML")
	}
}

// TestLoadAuthorityToleratesMissingScopeDirectory checks that a scope naming a
// directory that does not exist no longer refuses startup, because a policy may
// name a directory that has not been created yet and one absent directory must
// not stop a Node that serves several.
//
// The property the old test protected is kept, not dropped: the scope must not be
// advertised as served. It is asserted here as "defined, recorded, and refusing",
// which is the same guarantee expressed against the new behaviour. A scope that
// was silently skipped would pass a "startup succeeded" assertion and fail this
// one.
func TestLoadAuthorityToleratesMissingScopeDirectory(t *testing.T) {
	base := t.TempDir()
	absentPath := filepath.Join(base, "absent")
	policyPath := filepath.Join(base, "policy.yaml")
	writeFile(t, policyPath, "version: 1\n"+
		"scopes:\n"+
		"  project:\n"+
		"    path: "+absentPath+"\n"+
		"grants:\n"+
		"  - scope: project\n"+
		"    permissions: [read, list, stat]\n")

	authority, err := LoadAuthority(policyPath, nil, "")
	if err != nil {
		t.Fatalf("LoadAuthority() = %v, want nil for a missing scope directory", err)
	}
	defer authority.Close()

	scope, ok := authority.Scope(security.Scope("project"))
	if !ok {
		t.Fatal("Scope(project) reported missing, want the scope recorded so the policy and the served state agree")
	}
	if !scope.Absent() {
		t.Fatal("Absent() = false, want true for a scope whose directory does not exist")
	}
	if scope.ResolvedPath() != absentPath {
		t.Fatalf("ResolvedPath() = %q, want %q so the startup report names the path the operator must create", scope.ResolvedPath(), absentPath)
	}

	// The grant still exists, so the scope is authorized; the operation then
	// answers not_found because the directory does not.
	opened, err := authority.Authorize(security.Scope("project"), security.PermissionRead)
	if err != nil {
		t.Fatalf("Authorize(project, read) = %v, want nil because the grant exists", err)
	}
	if _, _, err := opened.Read("anything.txt", 0, 0); err == nil {
		t.Fatal("Read() = nil error, want not_found on a scope with no directory")
	} else if code := CodeOf(err); code != protocol.CodeNotFound {
		t.Fatalf("CodeOf(Read()) = %s, want not_found", code.Name())
	}
}

// TestLoadAuthorityRejectsScopePathThatIsAFile checks that a scope naming a
// regular file refuses startup, because a scope root must be a directory and a
// file root would make every path inside it meaningless.
func TestLoadAuthorityRejectsScopePathThatIsAFile(t *testing.T) {
	base := t.TempDir()
	filePath := filepath.Join(base, "not-a-directory")
	writeFile(t, filePath, "content")

	policyPath := filepath.Join(base, "policy.yaml")
	writeFile(t, policyPath, "version: 1\n"+
		"scopes:\n"+
		"  project:\n"+
		"    path: "+filePath+"\n")

	authority, err := LoadAuthority(policyPath, nil, "")
	if err == nil {
		authority.Close()
		t.Fatal("LoadAuthority() = nil error, want a failure for a file scope root")
	}
}

// TestLoadAuthorityClosesEarlierScopesOnFailure checks that a failure after one
// scope opened leaves no handle behind. The observable proof is that the
// directory can be removed, which a leaked handle would prevent on Windows and
// would hide on unix; the test therefore asserts the error and the removal.
//
// The second scope is a regular file rather than a missing directory, because a
// missing directory no longer fails startup. The property under test is handle
// cleanup on the failure path, so the failure has to be one that still fails.
func TestLoadAuthorityClosesEarlierScopesOnFailure(t *testing.T) {
	base := t.TempDir()
	first := filepath.Join(base, "first")
	if err := os.Mkdir(first, 0o755); err != nil {
		t.Fatalf("mkdir %q: %v", first, err)
	}
	notADirectory := filepath.Join(base, "not-a-directory")
	writeFile(t, notADirectory, "content")

	// The scopes are sorted, so `aaa` opens before `zzz` and the failure
	// happens after a handle exists.
	policyPath := filepath.Join(base, "policy.yaml")
	writeFile(t, policyPath, "version: 1\n"+
		"scopes:\n"+
		"  aaa:\n"+
		"    path: "+first+"\n"+
		"  zzz:\n"+
		"    path: "+notADirectory+"\n")

	authority, err := LoadAuthority(policyPath, nil, "")
	if err == nil {
		authority.Close()
		t.Fatal("LoadAuthority() = nil error, want a failure for the second scope")
	}
	if err := os.RemoveAll(first); err != nil {
		t.Fatalf("RemoveAll(%q) = %v, want nil; a leaked handle would block it", first, err)
	}
}

// TestLoadAuthorityRecordsDenyList checks that the Node's own files are refused
// by identity, so a request cannot read the policy file or the identity file even
// when they sit inside a scope.
func TestLoadAuthorityRecordsDenyList(t *testing.T) {
	fixture := newAuthorityFixture(t)

	secretPath := filepath.Join(fixture.project, "node.secret")
	writeFile(t, secretPath, "the node token")

	authority := fixture.load(t, []string{secretPath})

	scope, ok := authority.Scope(security.Scope("project"))
	if !ok {
		t.Fatal("Scope(project) reported missing, want present")
	}

	_, _, err := scope.Read("node.secret", 0, 0)
	if err == nil {
		t.Fatal("Read(node.secret) = nil error, want a refusal for a deny-listed file")
	}
	if code := CodeOf(err); code != protocol.CodeDenied {
		t.Fatalf("CodeOf(Read(node.secret)) = %v, want %v", code, protocol.CodeDenied)
	}

	// A file that is not deny-listed stays readable, so the deny list is a
	// filter rather than a blanket refusal.
	if _, _, err := scope.Read("inside.txt", 0, 0); err != nil {
		t.Fatalf("Read(inside.txt) = %v, want nil", err)
	}
}

// TestLoadAuthoritySkipsAbsentDenyPath checks that a deny path that does not
// exist yet is skipped rather than refused, because a Node that has not written
// its identity file must still be able to start.
func TestLoadAuthoritySkipsAbsentDenyPath(t *testing.T) {
	fixture := newAuthorityFixture(t)
	absent := filepath.Join(fixture.project, "not-written-yet")

	authority := fixture.load(t, []string{absent})
	if len(authority.ScopeNames()) != 2 {
		t.Fatalf("ScopeNames() = %v, want 2 names", authority.ScopeNames())
	}
}

// TestAuthorityAllowsFollowsThePolicy checks that the grant answer comes from the
// policy file and nowhere else.
func TestAuthorityAllowsFollowsThePolicy(t *testing.T) {
	fixture := newAuthorityFixture(t)
	authority := fixture.load(t, nil)

	cases := []struct {
		name       string
		scope      security.Scope
		permission security.Permission
		want       bool
	}{
		{"granted read", "project", security.PermissionRead, true},
		{"granted list", "project", security.PermissionList, true},
		{"granted stat", "project", security.PermissionStat, true},
		{"ungranted write", "project", security.PermissionWrite, false},
		{"ungranted exec", "project", security.PermissionExec, false},
		{"other scope list", "scratch", security.PermissionList, true},
		{"other scope read", "scratch", security.PermissionRead, false},
		{"undefined scope", "absent", security.PermissionRead, false},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := authority.Allows(testCase.scope, testCase.permission); got != testCase.want {
				t.Fatalf("Allows(%q, %q) = %v, want %v", testCase.scope, testCase.permission, got, testCase.want)
			}
		})
	}
}

// TestAuthorityAuthorizeReturnsTheScope checks that a granted call yields the
// scope to work in, so a dispatch path has one place to ask.
func TestAuthorityAuthorizeReturnsTheScope(t *testing.T) {
	fixture := newAuthorityFixture(t)
	authority := fixture.load(t, nil)

	scope, err := authority.Authorize(security.Scope("project"), security.PermissionRead)
	if err != nil {
		t.Fatalf("Authorize(project, read) = %v, want nil", err)
	}
	if scope == nil {
		t.Fatal("Authorize(project, read) = nil scope, want the open scope")
	}
	if scope.Name() != "project" {
		t.Fatalf("Name() = %q, want %q", scope.Name(), "project")
	}
}

// TestAuthorityAuthorizeRefusesWithoutGrant checks that a missing grant is a
// refusal carrying CodeDenied, and that the refusal is the same for an undefined
// scope, because the difference is a scope-name oracle.
func TestAuthorityAuthorizeRefusesWithoutGrant(t *testing.T) {
	fixture := newAuthorityFixture(t)
	authority := fixture.load(t, nil)

	cases := []struct {
		name       string
		scope      security.Scope
		permission security.Permission
	}{
		{"permission not granted", "project", security.PermissionWrite},
		{"scope not defined", "absent", security.PermissionRead},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			scope, err := authority.Authorize(testCase.scope, testCase.permission)
			if err == nil {
				t.Fatal("Authorize() = nil error, want a refusal")
			}
			if scope != nil {
				t.Fatal("Authorize() = non-nil scope, want nil on refusal")
			}
			if code := CodeOf(err); code != protocol.CodeDenied {
				t.Fatalf("CodeOf(Authorize()) = %v, want %v", code, protocol.CodeDenied)
			}
		})
	}
}

// TestAuthorityAuthorizeOperationMapsPermissions checks that each enabled
// operation consumes the permission the wire contract maps it to.
func TestAuthorityAuthorizeOperationMapsPermissions(t *testing.T) {
	fixture := newAuthorityFixture(t)
	authority := fixture.load(t, nil)

	cases := []struct {
		name      string
		operation protocol.Operation
		scope     security.Scope
		wantCode  protocol.Code
		wantOK    bool
	}{
		{"read granted", protocol.OperationFileRead, "project", protocol.CodeSuccess, true},
		{"list granted", protocol.OperationFileList, "project", protocol.CodeSuccess, true},
		{"stat granted", protocol.OperationFileStat, "project", protocol.CodeSuccess, true},
		{"read not granted on scratch", protocol.OperationFileRead, "scratch", protocol.CodeDenied, false},
		{"list granted on scratch", protocol.OperationFileList, "scratch", protocol.CodeSuccess, true},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			scope, err := authority.AuthorizeOperation(testCase.operation, testCase.scope)
			if testCase.wantOK {
				if err != nil {
					t.Fatalf("AuthorizeOperation(%q, %q) = %v, want nil", testCase.operation, testCase.scope, err)
				}
				if scope == nil {
					t.Fatal("AuthorizeOperation() = nil scope, want the open scope")
				}
				return
			}
			if err == nil {
				t.Fatal("AuthorizeOperation() = nil error, want a refusal")
			}
			if code := CodeOf(err); code != testCase.wantCode {
				t.Fatalf("CodeOf(AuthorizeOperation()) = %v, want %v", code, testCase.wantCode)
			}
		})
	}
}

// TestAuthorityAuthorizeOperationRefusesUnimplemented checks that an operation
// declared by the wire contract but not implemented in this version is refused at
// dispatch, so the read-only promise does not depend on the Server honouring what
// the Node advertised.
func TestAuthorityAuthorizeOperationRefusesUnimplemented(t *testing.T) {
	fixture := newAuthorityFixture(t)

	// The fixture grants read, list and stat only, so a write refusal could be
	// explained by the grant. The policy below grants write and exec as well, so
	// the refusal can only come from the version gate.
	writeFile(t, fixture.policyPath, "version: 1\n"+
		"scopes:\n"+
		"  project:\n"+
		"    path: "+fixture.project+"\n"+
		"grants:\n"+
		"  - scope: project\n"+
		"    permissions: [read, write, exec]\n")

	permissive := fixture.load(t, nil)

	for _, operation := range []protocol.Operation{protocol.OperationFileWrite, protocol.OperationCommandExec} {
		t.Run(string(operation), func(t *testing.T) {
			if permissive.Allows(security.Scope("project"), security.PermissionWrite) != true {
				t.Fatal("Allows(project, write) = false, want true; the fixture must grant it")
			}
			scope, err := permissive.AuthorizeOperation(operation, security.Scope("project"))
			if err == nil {
				t.Fatal("AuthorizeOperation() = nil error, want a refusal for an unimplemented operation")
			}
			if scope != nil {
				t.Fatal("AuthorizeOperation() = non-nil scope, want nil on refusal")
			}
			if code := CodeOf(err); code != protocol.CodeUnsupportedOperation {
				t.Fatalf("CodeOf(AuthorizeOperation()) = %v, want %v", code, protocol.CodeUnsupportedOperation)
			}
		})
	}
}

// TestAuthorityAuthorizeOperationRejectsUnknownOperation checks that a name
// outside the vocabulary is unsupported_operation, the same code an unimplemented
// operation gets.
//
// The two are deliberately collapsed. If an unknown name answered
// invalid_argument while a declared-but-disabled name answered
// unsupported_operation, a caller could enumerate the vocabulary by comparing the
// two codes, which is the same oracle the scope check refuses to provide.
func TestAuthorityAuthorizeOperationRejectsUnknownOperation(t *testing.T) {
	fixture := newAuthorityFixture(t)
	authority := fixture.load(t, nil)

	scope, err := authority.AuthorizeOperation(protocol.Operation("file.delete"), security.Scope("project"))
	if err == nil {
		t.Fatal("AuthorizeOperation(file.delete) = nil error, want a refusal")
	}
	if scope != nil {
		t.Fatal("AuthorizeOperation(file.delete) = non-nil scope, want nil")
	}
	if code := CodeOf(err); code != protocol.CodeUnsupportedOperation {
		t.Fatalf("CodeOf(AuthorizeOperation(file.delete)) = %v, want %v", code, protocol.CodeUnsupportedOperation)
	}
}

// TestAuthorityCloseIsIdempotent checks that a shutdown path that runs twice does
// not fail on the second call.
func TestAuthorityCloseIsIdempotent(t *testing.T) {
	fixture := newAuthorityFixture(t)
	authority, err := LoadAuthority(fixture.policyPath, nil, "")
	if err != nil {
		t.Fatalf("LoadAuthority() = %v, want nil", err)
	}

	if err := authority.Close(); err != nil {
		t.Fatalf("Close() = %v, want nil", err)
	}
	if err := authority.Close(); err != nil {
		t.Fatalf("second Close() = %v, want nil", err)
	}
}

// TestAuthorityCloseOnNilIsSafe checks that a nil Authority can be closed, so a
// startup failure path does not need a nil check at every call site.
func TestAuthorityCloseOnNilIsSafe(t *testing.T) {
	var authority *Authority
	if err := authority.Close(); err != nil {
		t.Fatalf("Close() on nil = %v, want nil", err)
	}
}

// TestAuthorityScopeReportsUndefined checks that an undefined scope is reported
// as missing rather than as a nil scope that exists.
func TestAuthorityScopeReportsUndefined(t *testing.T) {
	fixture := newAuthorityFixture(t)
	authority := fixture.load(t, nil)

	scope, ok := authority.Scope(security.Scope("absent"))
	if ok {
		t.Fatal("Scope(absent) reported present, want missing")
	}
	if scope != nil {
		t.Fatal("Scope(absent) = non-nil, want nil")
	}
}

// TestLoadAuthorityServesPresentScopesAlongsideAnAbsentOne checks that one absent
// scope does not stop the scopes that do exist, because the whole point of
// tolerating an absent directory is that a Node serving several scopes keeps
// serving the ones it can.
//
// The absent scope is asserted to be recorded and refusing, so "the Node started"
// is not mistaken for "the absent scope works".
func TestLoadAuthorityServesPresentScopesAlongsideAnAbsentOne(t *testing.T) {
	fixture := newAuthorityFixture(t)
	absentPath := filepath.Join(fixture.base, "absent")
	writeFile(t, fixture.policyPath, "version: 1\n"+
		"scopes:\n"+
		"  project:\n"+
		"    path: "+fixture.project+"\n"+
		"  absent:\n"+
		"    path: "+absentPath+"\n"+
		"grants:\n"+
		"  - scope: project\n"+
		"    permissions: [read, list, stat]\n"+
		"  - scope: absent\n"+
		"    permissions: [read, list, stat]\n")

	authority, err := LoadAuthority(fixture.policyPath, nil, "")
	if err != nil {
		t.Fatalf("LoadAuthority() = %v, want nil with one absent scope", err)
	}
	defer authority.Close()

	// The present scope still serves its file.
	opened, err := authority.Authorize(security.Scope("project"), security.PermissionRead)
	if err != nil {
		t.Fatalf("Authorize(project, read) = %v, want nil", err)
	}
	content, _, err := opened.Read("inside.txt", 0, 0)
	if err != nil {
		t.Fatalf("Read(inside.txt) = %v, want nil", err)
	}
	if string(content) != "inside content" {
		t.Fatalf("Read(inside.txt) = %q, want %q", content, "inside content")
	}

	// The absent scope is recorded, marked absent, and refuses.
	absent, ok := authority.Scope(security.Scope("absent"))
	if !ok {
		t.Fatal("Scope(absent) reported missing, want it recorded")
	}
	if !absent.Absent() {
		t.Fatal("Absent() = false, want true")
	}
	openedAbsent, err := authority.Authorize(security.Scope("absent"), security.PermissionRead)
	if err != nil {
		t.Fatalf("Authorize(absent, read) = %v, want nil because the grant exists", err)
	}
	if _, _, err := openedAbsent.Read("inside.txt", 0, 0); err == nil {
		t.Fatal("Read() = nil error, want not_found on an absent scope")
	} else if code := CodeOf(err); code != protocol.CodeNotFound {
		t.Fatalf("CodeOf(Read()) = %s, want not_found", code.Name())
	}
}

// TestAuthorizeRefusesAnAbsentScopeWithoutAGrant checks that the grant is checked
// before the directory is consulted, so a caller without the permission gets
// denied and learns nothing about whether the directory exists.
//
// The ordering is the property: if the absent scope answered not_found before the
// grant check, a caller could tell "this scope has no directory" from "you may not
// use this scope", which is a scope-state oracle.
func TestAuthorizeRefusesAnAbsentScopeWithoutAGrant(t *testing.T) {
	base := t.TempDir()
	policyPath := filepath.Join(base, "policy.yaml")
	writeFile(t, policyPath, "version: 1\n"+
		"scopes:\n"+
		"  absent:\n"+
		"    path: "+filepath.Join(base, "absent")+"\n"+
		"grants:\n"+
		"  - scope: absent\n"+
		"    permissions: [list]\n")

	authority, err := LoadAuthority(policyPath, nil, "")
	if err != nil {
		t.Fatalf("LoadAuthority() = %v, want nil", err)
	}
	defer authority.Close()

	// `read` is not granted, so the answer is denied even though the directory is
	// also missing. The grant check runs first.
	if _, err := authority.Authorize(security.Scope("absent"), security.PermissionRead); err == nil {
		t.Fatal("Authorize(absent, read) = nil error, want denied")
	} else if code := CodeOf(err); code != protocol.CodeDenied {
		t.Fatalf("CodeOf(Authorize()) = %s, want denied", code.Name())
	}

	// `list` is granted, so the scope is returned and the operation answers
	// not_found. The two answers differ because the two questions differ.
	opened, err := authority.Authorize(security.Scope("absent"), security.PermissionList)
	if err != nil {
		t.Fatalf("Authorize(absent, list) = %v, want nil because the grant exists", err)
	}
	if _, err := opened.List(""); err == nil {
		t.Fatal("List() = nil error, want not_found on an absent scope")
	} else if code := CodeOf(err); code != protocol.CodeNotFound {
		t.Fatalf("CodeOf(List()) = %s, want not_found", code.Name())
	}
}
