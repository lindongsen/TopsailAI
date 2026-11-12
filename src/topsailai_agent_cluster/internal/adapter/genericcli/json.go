package genericcli

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"strings"
)

func decodeStrictJSON(document []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(document))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("extra JSON document")
		}
		return err
	}
	return nil
}

func splitOutput(content string) []string {
	if content == "" {
		return nil
	}
	return strings.Split(strings.TrimSuffix(content, "\n"), "\n")
}
