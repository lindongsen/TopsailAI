// Package utils provides shared utility functions used across the ACS service.
package utils

import "golang.org/x/crypto/bcrypt"

// BcryptDefaultCost is the default bcrypt cost factor used for hashing group keys.
const BcryptDefaultCost = bcrypt.DefaultCost

// HashGroupKeyWithCost hashes a plaintext group key using bcrypt with the
// specified cost. Empty keys return an empty hash so public groups do not
// store a secret.
func HashGroupKeyWithCost(key string, cost int) (string, error) {
	if key == "" {
		return "", nil
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(key), cost)
	if err != nil {
		return "", err
	}
	return string(hash), nil
}

// HashGroupKey hashes a plaintext group key using bcrypt. Empty keys return an
// empty hash so public groups do not store a secret.
func HashGroupKey(key string) (string, error) {
	return HashGroupKeyWithCost(key, BcryptDefaultCost)
}

// VerifyGroupKey compares a plaintext group key against a bcrypt hash. Empty
// keys are considered valid only when the stored hash is also empty.
func VerifyGroupKey(key, hash string) bool {
	if hash == "" {
		return key == ""
	}
	if key == "" {
		return false
	}
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(key)) == nil
}
