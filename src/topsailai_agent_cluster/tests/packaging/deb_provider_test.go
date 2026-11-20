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
// moves the payload back to an unversioned path fails here instead of on a node
// where an Adapter is already running the previous version.
const (
	debProviderType      = "topsailai"
	debProviderVersion   = "0.0.0-test-1"
	debProviderRoot      = debOptDir + "/providers/" + debProviderType
	debProviderVersioned = debProviderRoot + "/" + debProviderVersion
	debProviderBinary    = debProviderVersioned + "/agent-cluster-provider-" + debProviderType
	debProviderManifest  = debProviderVersioned + "/manifest.json"
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

// TestDebProviderPayloadIsVersioned proves the Provider executable lives at a
// path that carries its package version.
//
// This is the property that makes an upgrade safe. An Adapter is configured with
// one executable path, so a package that overwrote a fixed path would replace the
// bytes an Adapter is currently running, and a rollback would need a rebuild
// instead of a path change. A versioned directory also lets two versions coexist,
// which is what the postinst retention policy bounds.
func TestDebProviderPayloadIsVersioned(t *testing.T) {
	pkg := debProviderPackage(t)

	entry, ok := pkg.entries[debProviderBinary]
	if !ok {
		t.Fatalf("missing %s in the Provider payload;\n"+
			"an unversioned path would overwrite the bytes an Adapter is running",
			debProviderBinary)
	}
	if entry.target != "" {
		t.Fatalf("%s must be a real file, not a symlink to %s", debProviderBinary, entry.target)
	}
	if entry.mode != "rwxr-xr-x" {
		t.Fatalf("%s has mode %q, want %q; the Endpoint executes it directly",
			debProviderBinary, entry.mode, "rwxr-xr-x")
	}

	// The version directory must be a real directory, not a symlink into a
	// shared location, because the retention policy removes whole directories.
	dir, ok := pkg.entries[debProviderVersioned]
	if !ok {
		t.Fatalf("missing the version directory %s", debProviderVersioned)
	}
	if dir.target != "" {
		t.Fatalf("%s must be a real directory, not a symlink to %s", debProviderVersioned, dir.target)
	}

	// A fixed path from an earlier layout must not survive beside the versioned
	// one, because two paths for one Provider make the active version ambiguous.
	for path := range pkg.entries {
		if path == debProviderRoot+"/agent-cluster-provider-"+debProviderType {
			t.Fatalf("the Provider package still ships the unversioned path %s", path)
		}
	}
}

// TestDebProviderManifestDescribesTheShippedBinary proves the manifest records
// the identity of the binary that is actually in the payload.
//
// The postinst compares the installed file against this digest, so a manifest
// that describes a different build would make every install fail, and a manifest
// with no digest would make the check vacuous.
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
		"provider_version":    "2.0.0",
		"descriptor_revision": "topsailai-provider-v3",
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

// TestDebProviderPostinstVerifiesIdentityAndBoundsRetention proves the maintainer
// script is specialised at build time and keeps the two safety properties.
//
// The placeholders are substituted by the builder, so an unsubstituted script
// would compare the installed binary against the literal string "@PROVIDER_TYPE@"
// and fail every install. The retention defaults are asserted because an
// unbounded retention policy is the failure mode that fills a disk slowly and is
// invisible until the filesystem is full.
func TestDebProviderPostinstVerifiesIdentityAndBoundsRetention(t *testing.T) {
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

	// Retention must be bounded by default and configurable.
	if !hasLineContaining(postinst, "AGENT_CLUSTER_PROVIDER_RETENTION_COUNT:-2") {
		t.Fatal("the postinst does not default the retention count to 2")
	}
	if !hasLineContaining(postinst, "AGENT_CLUSTER_PROVIDER_RETENTION_DAYS:-30") {
		t.Fatal("the postinst does not default the retention age to 30 days")
	}
	// The installed version must never be removed, otherwise the package stays
	// installed with no payload.
	if !hasLineContaining(postinst, `[ "${name}" = "${PACKAGE_VERSION}" ] && continue`) {
		t.Fatal("the postinst does not skip the version it just installed")
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
