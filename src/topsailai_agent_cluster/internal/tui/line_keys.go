package tui

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"unicode"
	"unicode/utf8"
)

const maxLineKeySequence = 32

var errLineKey = errors.New("unsupported or malformed terminal key")

type lineKeyKind uint8

const (
	lineKeyText lineKeyKind = iota
	lineKeyEnter
	lineKeyBackspace
	lineKeyDelete
	lineKeyLeft
	lineKeyRight
	lineKeyHome
	lineKeyEnd
	lineKeyPrevious
	lineKeyNext
	lineKeyInterrupt
	lineKeyEOF
)

type lineKey struct {
	kind lineKeyKind
	text rune
}

// readLineKey decodes one key; any error invalidates the caller's current line.
// The caller owns cancellation of reads, including an incomplete Escape sequence.
func readLineKey(reader *bufio.Reader) (lineKey, error) {
	r, size, err := reader.ReadRune()
	if err != nil {
		return lineKey{}, err
	}
	if r == utf8.RuneError && size == 1 {
		return lineKey{}, errLineKey
	}
	switch r {
	case 27:
		return readEscapeKey(reader)
	case '\r', '\n':
		return lineKey{kind: lineKeyEnter}, nil
	case 8, 127:
		return lineKey{kind: lineKeyBackspace}, nil
	case 1:
		return lineKey{kind: lineKeyHome}, nil
	case 5:
		return lineKey{kind: lineKeyEnd}, nil
	case 2:
		return lineKey{kind: lineKeyLeft}, nil
	case 6:
		return lineKey{kind: lineKeyRight}, nil
	case 16:
		return lineKey{kind: lineKeyPrevious}, nil
	case 14:
		return lineKey{kind: lineKeyNext}, nil
	case 3:
		return lineKey{kind: lineKeyInterrupt}, nil
	case 4:
		return lineKey{kind: lineKeyEOF}, nil
	}
	if unicode.IsControl(r) {
		return lineKey{}, errLineKey
	}
	return lineKey{kind: lineKeyText, text: r}, nil
}

// readEscapeKey caps all escape parsing work and rejects unrecognized sequences.
func readEscapeKey(reader *bufio.Reader) (lineKey, error) {
	prefix, err := reader.ReadByte()
	if err != nil {
		return lineKey{}, escapeKeyError(err)
	}
	if prefix != '[' && prefix != 'O' {
		return lineKey{}, errLineKey
	}
	sequence := make([]byte, 0, maxLineKeySequence)
	for len(sequence) < maxLineKeySequence {
		b, err := reader.ReadByte()
		if err != nil {
			return lineKey{}, escapeKeyError(err)
		}
		sequence = append(sequence, b)
		if b >= 0x40 && b <= 0x7e {
			return escapedLineKey(prefix, string(sequence))
		}
		if b < 0x20 || b > 0x3f {
			return lineKey{}, errLineKey
		}
	}
	return lineKey{}, fmt.Errorf("%w: escape exceeds %d bytes", errLineKey, maxLineKeySequence)
}

// escapeKeyError distinguishes truncated input from ordinary end of input.
func escapeKeyError(err error) error {
	if err == io.EOF {
		err = io.ErrUnexpectedEOF
	}
	return fmt.Errorf("%w: %w", errLineKey, err)
}

// escapedLineKey accepts only explicit cursor sequences, never pasted payloads.
func escapedLineKey(prefix byte, sequence string) (lineKey, error) {
	if prefix == '[' {
		switch sequence {
		case "1~", "7~":
			return lineKey{kind: lineKeyHome}, nil
		case "4~", "8~":
			return lineKey{kind: lineKeyEnd}, nil
		case "3~":
			return lineKey{kind: lineKeyDelete}, nil
		}
	}
	switch sequence {
	case "A":
		return lineKey{kind: lineKeyPrevious}, nil
	case "B":
		return lineKey{kind: lineKeyNext}, nil
	case "C":
		return lineKey{kind: lineKeyRight}, nil
	case "D":
		return lineKey{kind: lineKeyLeft}, nil
	case "H":
		return lineKey{kind: lineKeyHome}, nil
	case "F":
		return lineKey{kind: lineKeyEnd}, nil
	}
	return lineKey{}, errLineKey
}
