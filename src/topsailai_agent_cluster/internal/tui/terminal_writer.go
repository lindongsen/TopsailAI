package tui

import (
	"io"
	"strings"
	"unicode/utf8"
)

type safeWriter struct{ target io.Writer }

func newSafeWriter(target io.Writer) io.Writer { return &safeWriter{target: target} }

func (w *safeWriter) Write(data []byte) (int, error) {
	clean := sanitizeTerminal(data)
	if len(clean) == 0 {
		return len(data), nil
	}
	written := 0
	cleanBytes := []byte(clean)
	for written < len(cleanBytes) {
		n, err := w.target.Write(cleanBytes[written:])
		if n > 0 {
			written += n
		}
		if err != nil {
			return 0, err
		}
		if n == 0 {
			return 0, io.ErrShortWrite
		}
	}
	return len(data), nil
}

func sanitizeTerminal(data []byte) string {
	text := strings.ToValidUTF8(string(data), "�")
	var builder strings.Builder
	for len(text) > 0 {
		runeValue, size := utf8.DecodeRuneInString(text)
		text = text[size:]
		switch {
		case runeValue == '\n' || runeValue == '\t':
			builder.WriteRune(runeValue)
		case runeValue < 0x20 || runeValue == 0x7f || (runeValue >= 0x80 && runeValue <= 0x9f):
			builder.WriteRune('�')
		case runeValue >= 0x202a && runeValue <= 0x202e:
			builder.WriteRune('�')
		default:
			builder.WriteRune(runeValue)
		}
	}
	return builder.String()
}
