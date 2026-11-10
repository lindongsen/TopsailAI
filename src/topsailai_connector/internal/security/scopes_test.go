package security

import (
	"strings"
	"testing"
)

// TestGrantAllows checks that a grant authorizes only the permission it names
// and only on the scope it was issued for, so a read grant never authorizes a
// write and a grant on one scope never leaks to another.
func TestGrantAllows(t *testing.T) {
	grant := Grant{Scope: "project", Permissions: []Permission{PermissionRead}}

	cases := []struct {
		name       string
		scope      Scope
		permission Permission
		want       bool
	}{
		{name: "granted permission on granted scope", scope: "project", permission: PermissionRead, want: true},
		{name: "ungranted permission on granted scope", scope: "project", permission: PermissionWrite, want: false},
		{name: "granted permission on other scope", scope: "tool", permission: PermissionRead, want: false},
		{name: "exec is not implied by read", scope: "project", permission: PermissionExec, want: false},
		{name: "list is not implied by read", scope: "project", permission: PermissionList, want: false},
		{name: "stat is not implied by read", scope: "project", permission: PermissionStat, want: false},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := grant.Allows(testCase.scope, testCase.permission); got != testCase.want {
				t.Fatalf("Allows(%q, %q) = %v, want %v", testCase.scope, testCase.permission, got, testCase.want)
			}
		})
	}
}

// TestGrantAllowsEmptyGrant checks that a grant with no permissions authorizes
// nothing, so a misconfigured entry fails closed instead of open.
func TestGrantAllowsEmptyGrant(t *testing.T) {
	grant := Grant{Scope: "project"}
	if grant.Allows("project", PermissionRead) {
		t.Fatal("empty grant authorized a read, want denial")
	}
}

// TestGrantAllowsExactScopeMatch checks that a scope name is compared exactly,
// because a normalising comparison would make two different wire values address
// one scope.
func TestGrantAllowsExactScopeMatch(t *testing.T) {
	grant := Grant{Scope: "project", Permissions: []Permission{PermissionRead}}

	for _, scope := range []Scope{"Project", "project ", " project", "PROJECT"} {
		if grant.Allows(scope, PermissionRead) {
			t.Fatalf("Allows(%q, read) = true, want false", scope)
		}
	}
}

// TestValidateScopeName checks that a scope name is an identifier and never a
// path. The rule is a whitelist, so a character nobody thought to blacklist is
// still refused.
func TestValidateScopeName(t *testing.T) {
	cases := []struct {
		name    string
		scope   Scope
		wantErr bool
	}{
		{name: "plain name", scope: "project", wantErr: false},
		{name: "name with dash", scope: "work-notes", wantErr: false},
		{name: "name with underscore", scope: "work_notes", wantErr: false},
		{name: "name with digits", scope: "project2", wantErr: false},
		{name: "uppercase name", scope: "Project", wantErr: false},
		{name: "digits only", scope: "123", wantErr: false},
		{name: "empty name", scope: "", wantErr: true},
		{name: "forward slash", scope: "a/b", wantErr: true},
		{name: "backslash", scope: `a\b`, wantErr: true},
		{name: "dot", scope: ".", wantErr: true},
		{name: "dot dot", scope: "..", wantErr: true},
		{name: "leading dot", scope: ".project", wantErr: true},
		{name: "trailing dot", scope: "project.", wantErr: true},
		{name: "space", scope: "my project", wantErr: true},
		{name: "tab", scope: "my\tproject", wantErr: true},
		{name: "newline", scope: "my\nproject", wantErr: true},
		{name: "nul byte", scope: "pro\x00ject", wantErr: true},
		{name: "colon", scope: "pro:ject", wantErr: true},
		{name: "windows device name", scope: "CON", wantErr: false},
		{name: "leading dash", scope: "-project", wantErr: true},
		{name: "leading underscore", scope: "_project", wantErr: true},
		{name: "too long", scope: Scope(strings.Repeat("a", MaxScopeNameLength+1)), wantErr: true},
		{name: "exactly maximum length", scope: Scope(strings.Repeat("a", MaxScopeNameLength)), wantErr: false},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			err := ValidateScopeName(testCase.scope)
			if testCase.wantErr && err == nil {
				t.Fatalf("ValidateScopeName(%q) = nil, want error", testCase.scope)
			}
			if !testCase.wantErr && err != nil {
				t.Fatalf("ValidateScopeName(%q) = %v, want nil", testCase.scope, err)
			}
		})
	}
}

// TestValidateScopeNameRejectsControlCharacters checks the characters that reach
// a filesystem call in a form no policy author intended. Each of these was
// accepted by the previous blacklist implementation.
func TestValidateScopeNameRejectsControlCharacters(t *testing.T) {
	for _, scope := range []Scope{"a b", "a\tb", "a.", "a\x00b", "a:b"} {
		if err := ValidateScopeName(scope); err == nil {
			t.Fatalf("ValidateScopeName(%q) = nil, want error", scope)
		}
	}
}

// TestValidatePermission checks that an unknown permission is refused, because a
// guess in an authorization check is a grant.
func TestValidatePermission(t *testing.T) {
	for _, permission := range []Permission{
		PermissionRead, PermissionWrite, PermissionList, PermissionStat, PermissionExec,
	} {
		if err := ValidatePermission(permission); err != nil {
			t.Fatalf("ValidatePermission(%q) = %v, want nil", permission, err)
		}
	}

	for _, permission := range []Permission{"", "fly", "READ", "read ", "*"} {
		if err := ValidatePermission(permission); err == nil {
			t.Fatalf("ValidatePermission(%q) = nil, want error", permission)
		}
	}
}

// TestIsIdentifier checks the yes-or-no helper agrees with the error-returning
// validator, because two answers to one question is how they drift apart.
func TestIsIdentifier(t *testing.T) {
	for _, value := range []string{"project", "work-notes", "", "a/b", "a b", ".."} {
		want := ValidateScopeName(Scope(value)) == nil
		if got := IsIdentifier(value); got != want {
			t.Fatalf("IsIdentifier(%q) = %v, want %v", value, got, want)
		}
	}
}
