package node

import (
	"os"
	"strings"
	"testing"

	"topsailai_connector/internal/security"
)

// TestEnsureIdentityWithSeedWritesTheSeedOnFirstStart pins the property the
// packaging feature rests on: a build that embedded an address answers to that
// address on its first start, so the operator knows it before shipping.
func TestEnsureIdentityWithSeedWritesTheSeedOnFirstStart(t *testing.T) {
	_, identityPath := newIdentityFixture(t)

	seed, err := security.NewNodeID()
	if err != nil {
		t.Fatalf("generate a seed: %v", err)
	}

	nodeID, generated, err := EnsureIdentityWithSeed(identityPath, seed)
	if err != nil {
		t.Fatalf("EnsureIdentityWithSeed: %v", err)
	}
	if !generated {
		t.Fatal("generated = false for a first start that wrote the seed")
	}
	if nodeID != seed {
		t.Fatalf("node id = %q, want the seed %q", nodeID, seed)
	}

	// The file must hold the seed, not only the return value: the running Node reads
	// the file on every start and the identity watcher polls it.
	stored, err := LoadIdentity(identityPath)
	if err != nil {
		t.Fatalf("LoadIdentity: %v", err)
	}
	if stored != seed {
		t.Fatalf("stored identity = %q, want the seed %q", stored, seed)
	}
}

// TestEnsureIdentityWithSeedLetsTheFileWin is the property that keeps `regenerate`
// working. A Node that preferred the seed would answer to the retired address again
// after a restart, and the operator would see a routing failure with no cause.
func TestEnsureIdentityWithSeedLetsTheFileWin(t *testing.T) {
	_, identityPath := newIdentityFixture(t)

	seed, err := security.NewNodeID()
	if err != nil {
		t.Fatalf("generate a seed: %v", err)
	}
	if _, _, err := EnsureIdentityWithSeed(identityPath, seed); err != nil {
		t.Fatalf("first start: %v", err)
	}

	regenerated, err := RegenerateIdentity(identityPath)
	if err != nil {
		t.Fatalf("RegenerateIdentity: %v", err)
	}
	if regenerated == seed {
		t.Fatal("regeneration produced the seed again; the test cannot distinguish the two")
	}

	nodeID, generated, err := EnsureIdentityWithSeed(identityPath, seed)
	if err != nil {
		t.Fatalf("second start: %v", err)
	}
	if generated {
		t.Fatal("generated = true for a start that found an existing file")
	}
	if nodeID != regenerated {
		t.Fatalf("node id = %q, want the regenerated %q; the seed overrode the file", nodeID, regenerated)
	}
}

// TestEnsureIdentityWithSeedRejectsAMalformedSeed checks that a packaging mistake is
// a startup failure rather than a silent fallback to a random address. A random
// address would look like a working Node whose address the operator cannot find.
func TestEnsureIdentityWithSeedRejectsAMalformedSeed(t *testing.T) {
	_, identityPath := newIdentityFixture(t)

	if _, _, err := EnsureIdentityWithSeed(identityPath, "not-a-node-id"); err == nil {
		t.Fatal("EnsureIdentityWithSeed accepted a malformed seed")
	}
	if _, err := os.Stat(identityPath); !os.IsNotExist(err) {
		t.Fatalf("a rejected seed left an identity file behind: %v", err)
	}
}

// TestEnsureCredentialsWithSeedWritesTheSeedOnFirstStart pins the same property for
// the credential: the secret the operator recorded at packaging time is the secret
// the Node accepts.
func TestEnsureCredentialsWithSeedWritesTheSeedOnFirstStart(t *testing.T) {
	configDir := t.TempDir()
	credentialsPath := CredentialsPath(configDir)

	seed, err := security.NewCredentialWithKeyID("packaged-caller")
	if err != nil {
		t.Fatalf("generate a seed: %v", err)
	}

	set, generated, err := EnsureCredentialsWithSeed(credentialsPath, seed)
	if err != nil {
		t.Fatalf("EnsureCredentialsWithSeed: %v", err)
	}
	if generated == nil {
		t.Fatal("generated = nil for a first start that wrote the seed")
	}
	if generated.KeyID != seed.KeyID || generated.Secret != seed.Secret {
		t.Fatalf("generated = %s, want the seed %s", generated.Redacted(), seed.Redacted())
	}

	// The seed must be usable for authentication, not merely stored.
	looked, ok := set.Lookup(seed.KeyID)
	if !ok {
		t.Fatalf("the seeded key id %q is not in the set", seed.KeyID)
	}
	if looked != seed.Secret {
		t.Fatal("the seeded secret does not verify against the stored set")
	}
}

// TestEnsureCredentialsWithSeedLetsTheFileWin keeps `credential remove` meaningful.
// A Node that preferred the seed would restore a revoked caller on every restart.
func TestEnsureCredentialsWithSeedLetsTheFileWin(t *testing.T) {
	configDir := t.TempDir()
	credentialsPath := CredentialsPath(configDir)

	seed, err := security.NewCredentialWithKeyID("packaged-caller")
	if err != nil {
		t.Fatalf("generate a seed: %v", err)
	}
	if _, _, err := EnsureCredentialsWithSeed(credentialsPath, seed); err != nil {
		t.Fatalf("first start: %v", err)
	}

	// Replace the set with a different credential, which is what `credential remove`
	// followed by `credential add` leaves behind.
	replacement, err := security.NewCredentialWithKeyID("replacement-caller")
	if err != nil {
		t.Fatalf("generate a replacement: %v", err)
	}
	if err := SaveCredentials(credentialsPath, []security.Credential{replacement}); err != nil {
		t.Fatalf("SaveCredentials: %v", err)
	}

	set, generated, err := EnsureCredentialsWithSeed(credentialsPath, seed)
	if err != nil {
		t.Fatalf("second start: %v", err)
	}
	if generated != nil {
		t.Fatal("generated is not nil for a start that found an existing file")
	}
	if _, ok := set.Lookup(seed.KeyID); ok {
		t.Fatal("the seed was restored over the file; a revoked caller would work again")
	}
	if _, ok := set.Lookup(replacement.KeyID); !ok {
		t.Fatal("the replacement credential is missing from the set")
	}
}

// TestEnsureCredentialsWithSeedRejectsAMalformedSeed checks that a packaging mistake
// is a startup failure rather than a different secret. A different secret would hand
// the operator a value that does not authenticate, and the failure would appear on
// the recipient's machine.
func TestEnsureCredentialsWithSeedRejectsAMalformedSeed(t *testing.T) {
	configDir := t.TempDir()
	credentialsPath := CredentialsPath(configDir)

	// A credential with no dot cannot be parsed, so it cannot be a seed.
	if _, _, err := EnsureCredentialsWithSeed(credentialsPath, security.Credential{KeyID: "no-secret"}); err == nil {
		t.Fatal("EnsureCredentialsWithSeed accepted a credential with no secret")
	}
	if _, err := os.Stat(credentialsPath); !os.IsNotExist(err) {
		t.Fatalf("a rejected seed left a credential file behind: %v", err)
	}
}

// TestEnsureIdentityWithoutASeedStillGenerates keeps the default path honest: a
// build that embedded nothing must behave exactly as it did before seeds existed.
func TestEnsureIdentityWithoutASeedStillGenerates(t *testing.T) {
	_, identityPath := newIdentityFixture(t)

	nodeID, generated, err := EnsureIdentityWithSeed(identityPath, "")
	if err != nil {
		t.Fatalf("EnsureIdentityWithSeed: %v", err)
	}
	if !generated {
		t.Fatal("generated = false for a first start with no seed")
	}
	if err := security.ValidateNodeID(nodeID); err != nil {
		t.Fatalf("the generated id is not valid: %v", err)
	}
	if strings.TrimSpace(nodeID) != nodeID {
		t.Fatal("the generated id carries whitespace")
	}
}
