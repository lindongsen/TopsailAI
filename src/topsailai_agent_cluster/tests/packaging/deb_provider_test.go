package packaging_test

import (
	"crypto/sha256"
	"encoding/hex"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// The Provider CLI package is optional and independent of every role package.
// These constants pin the layout it must produce, so a packaging change that
// moves the payload back to a versioned path fails here instead of on a node
// where every site configuration would then name a directory that no longer
// exists.
const (
	debProviderType     = "topsailai"
	debProviderVersion  = "0.0.0-test-1"
	debProviderRoot     = debOptDir + "/providers/" + debProviderType
	debProviderBinary   = debProviderRoot + "/agent-cluster-provider-" + debProviderType
	debProviderManifest = debProviderRoot + "/manifest.json"
)

// debProviderPackage returns the built Provider package. The build itself is
// shared with the other packaging tests, so this only selects the entry.
func debProviderPackage(t *testing.T) *debPackage {
	t.Helper()
	packages := buildDebPackages(t)
	pkg, ok := packages["provider-topsailai"]
	if !ok {
		t.Fatal("the Provider package was not built")
	}
	return pkg
}

// readControlFile returns one member of a package control archive. conffiles is
// read by readConffiles, but postinst and the other maintainer scripts need the
// same treatment, so this helper keeps the tar invocation in one place.
func readControlFile(t *testing.T, pkg *debPackage, path string) string {
	t.Helper()
	control, err := exec.Command("dpkg-deb", "--ctrl-tarfile", pkg.path).Output()
	if err != nil {
		t.Fatalf("cannot read the control archive of %s: %v", pkg.path, err)
	}
	command := exec.Command("tar", "-xO", path)
	command.Stdin = strings.NewReader(string(control))
	output, err := command.Output()
	if err != nil {
		t.Fatalf("cannot extract %s from the control archive of %s: %v", path, pkg.path, err)
	}
	return string(output)
}

// TestDebProviderPayloadIsAtAFixedPath proves the Provider executable lives at a
// path that carries no version.
//
// The fixed path is what lets one site configuration name one executable forever.
// A versioned directory wrote the package version into every node.conf, so each
// Provider release required a configuration package rebuild, and a forgotten
// rewrite left a healthy Endpoint running the previous binary with no error. The
// accepted cost is that installing this package replaces the bytes an Adapter
// runs, so a rollback is a reinstall rather than a path change.
func TestDebProviderPayloadIsAtAFixedPath(t *testing.T) {
	pkg := debProviderPackage(t)

	entry, ok := pkg.entries[debProviderBinary]
	if !ok {
		t.Fatalf("missing %s in the Provider payload;\n"+
			"a versioned path would force every site configuration to name the version",
			debProviderBinary)
	}
	if entry.target != "" {
		t.Fatalf("%s must be a real file, not a symlink to %s", debProviderBinary, entry.target)
	}
	if entry.mode != "rwxr-xr-x" {
		t.Fatalf("%s has mode %q, want %q; the Endpoint executes it directly",
			debProviderBinary, entry.mode, "rwxr-xr-x")
	}

	// No version directory may survive beside the fixed path. Two paths for one
	// Provider would make the active executable ambiguous, and the versioned one
	// would be the path an older configuration still names.
	versionPrefix := debProviderRoot + "/" + debProviderVersion
	for path := range pkg.entries {
		if path == versionPrefix || strings.HasPrefix(path, versionPrefix+"/") {
			t.Fatalf("the Provider package still ships the versioned path %s;\n"+
				"the payload must live at %s only", path, debProviderBinary)
		}
	}
}

// TestDebProviderManifestDescribesTheShippedBinary proves the manifest records
// the identity of the binary that is actually in the payload.
//
// The postinst compares the installed file against this digest, so a manifest
// that describes a different build would make every install fail, and a manifest
// with no digest would make the check vacuous. The manifest sits beside the binary
// it describes, so a fixed path cannot separate the two.
func TestDebProviderManifestDescribesTheShippedBinary(t *testing.T) {
	pkg := debProviderPackage(t)

	entry, ok := pkg.entries[debProviderManifest]
	if !ok {
		t.Fatalf("missing %s in the Provider payload", debProviderManifest)
	}
	if entry.mode != "rw-r--r--" {
		t.Fatalf("%s has mode %q, want %q", debProviderManifest, entry.mode, "rw-r--r--")
	}

	manifest := readPackagedFile(t, pkg, debProviderManifest)
	for field, want := range map[string]string{
		"provider_type":       debProviderType,
		"provider_version":    debTestVersion,
		"descriptor_revision": "topsailai-provider-v4",
		"protocol":            "agent-cluster-adapter",
		"package_version":     debProviderVersion,
	} {
		if !strings.Contains(manifest, `"`+field+`": "`+want+`"`) {
			t.Fatalf("the manifest does not record %s=%q:\n%s", field, want, manifest)
		}
	}

	// The digest must match the shipped bytes. Comparing against the payload
	// rather than against a recorded constant is what makes this a real check:
	// a stale manifest and a rebuilt binary disagree here.
	digestPattern := regexp.MustCompile(`"sha256": "([0-9a-f]{64})"`)
	match := digestPattern.FindStringSubmatch(manifest)
	if match == nil {
		t.Fatalf("the manifest carries no 64-character sha256:\n%s", manifest)
	}
	binary := readPackagedFile(t, pkg, debProviderBinary)
	sum := sha256.Sum256([]byte(binary))
	if got := hex.EncodeToString(sum[:]); got != match[1] {
		t.Fatalf("the manifest sha256 %s does not match the shipped binary digest %s;\n"+
			"the postinst would reject every install of this package", match[1], got)
	}
}

// TestDebProviderPackageDependsOnNoRole proves the Provider package installs on a
// machine that has no Endpoint and no controller.
//
// A Provider CLI is a standalone executable the Endpoint invokes, so a dependency
// on a role package would make the Provider uninstallable on its own and would
// couple a Provider release to a cluster release. The dependency is also the
// place where a Provider-specific coupling would hide, because dpkg resolves it
// silently at install time.
func TestDebProviderPackageDependsOnNoRole(t *testing.T) {
	pkg := debProviderPackage(t)

	for _, want := range []string{"bash (>= 4.0)", "coreutils"} {
		if !strings.Contains(pkg.depends, want) {
			t.Fatalf("the Provider package Depends %q does not name %q;\n"+
				"the postinst needs both to verify the installed binary", pkg.depends, want)
		}
	}
	for _, forbidden := range []string{"agent-cluster-node", "agent-cluster-endpoint", "agent-cluster-server"} {
		if strings.Contains(pkg.depends, forbidden) {
			t.Fatalf("the Provider package Depends %q names %q;\n"+
				"a Provider CLI must install without any role package", pkg.depends, forbidden)
		}
	}
	if pkg.provides != "" {
		t.Fatalf("the Provider package Provides %q; a Provider is not a virtual role", pkg.provides)
	}
}

// TestDebProviderPostinstVerifiesIdentity proves the maintainer script is
// specialised at build time and keeps both identity checks.
//
// The placeholders are substituted by the builder, so an unsubstituted script
// would compare the installed binary against the literal string "@PROVIDER_TYPE@"
// and fail every install. The digest check and the describe probe are the only
// proof that the bytes at the fixed path are the packaged bytes, which matters
// more with a fixed path than with a versioned one: dpkg accepts a same-version
// replacement silently, so the path alone proves nothing.
func TestDebProviderPostinstVerifiesIdentity(t *testing.T) {
	pkg := debProviderPackage(t)
	postinst := readControlFile(t, pkg, "./postinst")

	for _, placeholder := range []string{"@PROVIDER_TYPE@", "@PACKAGE_VERSION@"} {
		if strings.Contains(postinst, placeholder) {
			t.Fatalf("the postinst still carries the placeholder %s;\n"+
				"the identity check would compare against a literal placeholder", placeholder)
		}
	}
	if !hasLineContaining(postinst, `PROVIDER_TYPE="`+debProviderType+`"`) {
		t.Fatal("the postinst does not carry the specialised provider type")
	}
	if !hasLineContaining(postinst, `PACKAGE_VERSION="`+debProviderVersion+`"`) {
		t.Fatal("the postinst does not carry the specialised package version")
	}

	// The digest check and the describe probe are the two identity checks. Both
	// are asserted structurally, because a mention of sha256sum is not a check.
	if !hasLineContaining(postinst, "sha256sum", "BINARY") {
		t.Fatal("the postinst never compares the installed binary digest")
	}
	if !hasLineContaining(postinst, "describe", "BINARY") {
		t.Fatal("the postinst never runs describe against the installed binary")
	}

	// The manifest reader must accept the spacing the builder actually writes.
	// The builder emits `"sha256": "<digest>"` with a space after the colon, so a
	// pattern that requires `"sha256":"<digest>"` matches nothing and the
	// postinst aborts every install with "the manifest carries no sha256".
	//
	// This runs the postinst's own sed expression against the manifest the
	// builder produced, because a pattern assertion cannot distinguish the two
	// forms: `[[:space:]]*` matches zero spaces, so a regexp check passes on the
	// broken pattern as well. Only executing the expression proves the reader
	// and the writer agree.
	manifest := readPackagedFile(t, pkg, debProviderManifest)
	for _, field := range []string{"sha256", "provider_version"} {
		expression := postinstSedExpression(t, postinst, field)
		command := exec.Command("sed", "-n", expression)
		command.Stdin = strings.NewReader(manifest)
		output, err := command.Output()
		if err != nil {
			t.Fatalf("cannot run the postinst sed expression for %q: %v", field, err)
		}
		if strings.TrimSpace(string(output)) == "" {
			t.Fatalf("the postinst reads %q with an expression that matches nothing in the manifest it ships beside;\n"+
				"the builder writes `\"%s\": \"...\"` with a space after the colon, so every install aborts", field, field)
		}
	}
}

// TestDebProviderPostinstDeletesNothing proves the maintainer script carries no
// retention policy.
//
// A fixed path has no superseded directory to retire, so a retention block would
// be dead code that still runs `rm -rf` against a directory listing. The failure
// mode of a wrong retention setting is an unbounded delete, and the failure mode
// of a leftover block is a delete nobody expects, so the absence is asserted
// rather than assumed.
func TestDebProviderPostinstDeletesNothing(t *testing.T) {
	pkg := debProviderPackage(t)
	postinst := readControlFile(t, pkg, "./postinst")

	for _, forbidden := range []string{
		"AGENT_CLUSTER_PROVIDER_RETENTION_COUNT",
		"AGENT_CLUSTER_PROVIDER_RETENTION_DAYS",
		"rm -rf",
	} {
		if strings.Contains(postinst, forbidden) {
			t.Fatalf("the postinst still carries %q;\n"+
				"a fixed payload path has no superseded version to retire, so the script must delete nothing",
				forbidden)
		}
	}
}

// TestDebProviderPackageShipsNoMock proves the test-only Mock Provider never
// reaches a release artifact.
//
// The Mock Provider exists to verify the protocol without a real provider, so it
// is a test double. Shipping it would put a second executable on a node that
// answers the same protocol, and an operator could point an Adapter at it by
// mistake.
func TestDebProviderPackageShipsNoMock(t *testing.T) {
	pkg := debProviderPackage(t)

	for path := range pkg.entries {
		if strings.Contains(path, "mock") {
			t.Fatalf("the Provider package ships the test-only Mock Provider at %s", path)
		}
	}

	// The package name must identify the Provider type, so two Provider packages
	// never collide in one dpkg database.
	base := filepath.Base(pkg.path)
	if !strings.HasPrefix(base, "agent-cluster-provider-"+debProviderType+"_") {
		t.Fatalf("the Provider package file is %q, want a name starting with %q",
			base, "agent-cluster-provider-"+debProviderType+"_")
	}
	if strings.Contains(base, ":") {
		t.Fatalf("the Provider package file name %q contains a colon; the epoch belongs "+
			"in the control Version field only", base)
	}
}
