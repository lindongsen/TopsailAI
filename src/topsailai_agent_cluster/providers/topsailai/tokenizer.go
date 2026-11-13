package main

import (
	"sync"

	tiktoken "github.com/pkoukk/tiktoken-go"
	tiktokenloader "github.com/pkoukk/tiktoken-go-loader"
)

const providerTokenEncoding = "cl100k_base"

var (
	providerEncodingOnce sync.Once
	providerEncoding     *tiktoken.Tiktoken
)

// loadProviderEncoding returns the offline tokenizer used by the TopsailAI
// human-readable message surface. Failure degrades to an omitted count.
func loadProviderEncoding() *tiktoken.Tiktoken {
	providerEncodingOnce.Do(func() {
		tiktoken.SetBpeLoader(tiktokenloader.NewOfflineLoader())
		loaded, err := tiktoken.GetEncoding(providerTokenEncoding)
		if err == nil {
			providerEncoding = loaded
		}
	})
	return providerEncoding
}

// tokenCount counts the raw stored Provider body with the Provider's own rule.
func tokenCount(value string) int {
	if value == "" {
		return 0
	}
	encoding := loadProviderEncoding()
	if encoding == nil {
		return 0
	}
	return len(encoding.EncodeOrdinary(value))
}
