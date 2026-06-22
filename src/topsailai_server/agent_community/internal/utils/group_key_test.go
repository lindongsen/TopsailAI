package utils

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestHashGroupKey_EmptyReturnsEmpty(t *testing.T) {
	hash, err := HashGroupKey("")
	require.NoError(t, err)
	assert.Empty(t, hash)
}

func TestHashGroupKey_ReturnsBcryptHash(t *testing.T) {
	hash, err := HashGroupKey("my-secret-key")
	require.NoError(t, err)
	assert.NotEmpty(t, hash)
	assert.NotEqual(t, "my-secret-key", hash)
	assert.True(t, len(hash) >= 50)
	assert.True(t, hash[0] == '$')
}

func TestVerifyGroupKey_EmptyStoredHash(t *testing.T) {
	assert.True(t, VerifyGroupKey("", ""))
	assert.False(t, VerifyGroupKey("", "any-key"))
}

func TestVerifyGroupKey_MissingProvidedKey(t *testing.T) {
	hash, err := HashGroupKey("secret")
	require.NoError(t, err)
	assert.False(t, VerifyGroupKey(hash, ""))
}

func TestVerifyGroupKey_CorrectKey(t *testing.T) {
	hash, err := HashGroupKey("correct-key")
	require.NoError(t, err)
	assert.True(t, VerifyGroupKey("correct-key", hash))
	assert.False(t, VerifyGroupKey("wrong-key", hash))
}
