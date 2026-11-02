package tui

import (
	"io"
	"strings"
	"unicode/utf8"
)

const maxTerminalSequenceBytes = 4096

type terminalSequenceState uint8

const (
	terminalNormal terminalSequenceState = iota
	terminalEscape
	terminalCSI
	terminalOSC
	terminalOSCEscape
	terminalDiscard
)

type safeWriter struct {
	target       io.Writer
	state        terminalSequenceState
	utf8Pending  []byte
	sequenceSize int
}

func newSafeWriter(target io.Writer) *safeWriter { return &safeWriter{target: target} }

func (w *safeWriter) Write(data []byte) (int, error) {
	var clean strings.Builder
	for _, value := range data {
		w.consume(value, &clean)
	}
	if err := w.writeAll([]byte(clean.String())); err != nil {
		return 0, err
	}
	return len(data), nil
}

func (w *safeWriter) Flush() error {
	if len(w.utf8Pending) > 0 {
		w.utf8Pending = nil
		if err := w.writeAll([]byte(string(utf8.RuneError))); err != nil {
			return err
		}
	}
	w.state = terminalNormal
	w.sequenceSize = 0
	return nil
}

func (w *safeWriter) consume(value byte, clean *strings.Builder) {
	if w.state != terminalNormal {
		w.consumeSequence(value)
		return
	}
	if len(w.utf8Pending) > 0 {
		w.utf8Pending = append(w.utf8Pending, value)
		if !utf8.FullRune(w.utf8Pending) {
			return
		}
		w.consumeRune(clean)
		if len(w.utf8Pending) > 0 {
			remaining := append([]byte(nil), w.utf8Pending...)
			w.utf8Pending = nil
			for _, pendingByte := range remaining {
				w.consume(pendingByte, clean)
			}
		}
		return
	}
	if value == 0x1b {
		w.state = terminalEscape
		w.sequenceSize = 1
		return
	}
	if value < utf8.RuneSelf {
		writeSafeASCII(clean, value)
		return
	}
	w.utf8Pending = append(w.utf8Pending, value)
	if utf8.FullRune(w.utf8Pending) {
		w.consumeRune(clean)
	}
}
func (w *safeWriter) consumeSequence(value byte) {
	if w.sequenceSize < maxTerminalSequenceBytes {
		w.sequenceSize++
	}
	if w.sequenceSize >= maxTerminalSequenceBytes {
		w.state = terminalDiscard
		return
	}
	switch w.state {
	case terminalEscape:
		switch value {
		case '[':
			w.state = terminalCSI
		case ']':
			w.state = terminalOSC
		default:
			w.state = terminalNormal
			w.sequenceSize = 0
		}
	case terminalCSI:
		if value >= 0x40 && value <= 0x7e {
			w.state = terminalNormal
			w.sequenceSize = 0
		}
	case terminalOSC:
		if value == 0x07 {
			w.state = terminalNormal
			w.sequenceSize = 0
		} else if value == 0x1b {
			w.state = terminalOSCEscape
		}
	case terminalOSCEscape:
		if value == '\\' || value == 0x07 {
			w.state = terminalNormal
			w.sequenceSize = 0
		} else {
			w.state = terminalOSC
		}
	case terminalDiscard:
		if value == 0x07 {
			w.state = terminalNormal
			w.sequenceSize = 0
		} else if value == 0x1b {
			w.state = terminalOSCEscape
		}
	}
}

func (w *safeWriter) consumeRune(clean *strings.Builder) {
	runeValue, size := utf8.DecodeRune(w.utf8Pending)
	if runeValue == utf8.RuneError && size == 1 {
		clean.WriteRune('�')
		w.utf8Pending = w.utf8Pending[1:]
		return
	}
	w.utf8Pending = w.utf8Pending[size:]
	if isSafeTerminalRune(runeValue) {
		clean.WriteRune(runeValue)
	}
}

func (w *safeWriter) writeAll(data []byte) error {
	written := 0
	for written < len(data) {
		n, err := w.target.Write(data[written:])
		if n > 0 {
			written += n
		}
		if err != nil {
			return err
		}
		if n == 0 {
			return io.ErrShortWrite
		}
	}
	return nil
}

func writeSafeASCII(clean *strings.Builder, value byte) {
	switch value {
	case '\n', '\t':
		clean.WriteByte(value)
	case 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f,
		0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e, 0x1f, 0x7f:
		clean.WriteRune('�')
	default:
		clean.WriteByte(value)
	}
}

func isSafeTerminalRune(value rune) bool {
	if value < 0x20 || (value >= 0x7f && value <= 0x9f) {
		return false
	}
	if value >= 0x202a && value <= 0x202e {
		return false
	}
	if value >= 0x2066 && value <= 0x2069 {
		return false
	}
	switch value {
	case 0x061c, 0x200b, 0x200c, 0x200d, 0x200e, 0x200f, 0x2060:
		return false
	}
	return true
}

func sanitizeTerminal(data []byte) string {
	var output strings.Builder
	writer := &safeWriter{target: &output}
	_, _ = writer.Write(data)
	_ = writer.Flush()
	return output.String()
}
