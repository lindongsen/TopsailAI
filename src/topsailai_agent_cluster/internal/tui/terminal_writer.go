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
	// keepSGR preserves colour-only SGR sequences instead of dropping every
	// escape sequence. It never widens the allow list beyond SGR, so cursor
	// movement, title changes and hyperlinks stay stripped.
	keepSGR bool
	// sequence buffers the escape sequence currently being consumed, so a
	// completed SGR sequence can be replayed verbatim when keepSGR is set.
	sequence []byte
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
	w.sequence = nil
	return nil
}

func (w *safeWriter) consume(value byte, clean *strings.Builder) {
	if w.state != terminalNormal {
		w.consumeSequence(value, clean)
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
		w.sequence = append(w.sequence[:0], value)
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
func (w *safeWriter) consumeSequence(value byte, clean *strings.Builder) {
	if w.sequenceSize < maxTerminalSequenceBytes {
		w.sequenceSize++
	}
	if w.sequenceSize >= maxTerminalSequenceBytes {
		w.state = terminalDiscard
		w.sequence = nil
		return
	}
	if len(w.sequence) < maxTerminalSequenceBytes {
		w.sequence = append(w.sequence, value)
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
			w.sequence = nil
		}
	case terminalCSI:
		if value >= 0x40 && value <= 0x7e {
			if w.keepSGR && isSGRSequence(w.sequence) {
				clean.Write(w.sequence)
			}
			w.state = terminalNormal
			w.sequenceSize = 0
			w.sequence = nil
		}
	case terminalOSC:
		if value == 0x07 {
			w.state = terminalNormal
			w.sequenceSize = 0
			w.sequence = nil
		} else if value == 0x1b {
			w.state = terminalOSCEscape
		}
	case terminalOSCEscape:
		if value == '\\' || value == 0x07 {
			w.state = terminalNormal
			w.sequenceSize = 0
			w.sequence = nil
		} else {
			w.state = terminalOSC
		}
	case terminalDiscard:
		if value == 0x07 {
			w.state = terminalNormal
			w.sequenceSize = 0
			w.sequence = nil
		} else if value == 0x1b {
			w.state = terminalOSCEscape
		}
	}
}

// isSGRSequence reports whether sequence is a complete colour-only SGR
// sequence of the form ESC [ <digits, ';' or ':'> m. Anything else, including
// private modes and cursor controls, is rejected so the allow list stays
// limited to styling.
func isSGRSequence(sequence []byte) bool {
	if len(sequence) < 3 || sequence[0] != 0x1b || sequence[1] != '[' {
		return false
	}
	if sequence[len(sequence)-1] != 'm' {
		return false
	}
	for _, value := range sequence[2 : len(sequence)-1] {
		if value >= '0' && value <= '9' {
			continue
		}
		if value == ';' || value == ':' {
			continue
		}
		return false
	}
	return true
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

// filterProviderOutput sanitizes untrusted provider output for terminal display.
// Dangerous sequences are always removed. SGR colour survives only when the
// colour policy is enabled, so a redirected or --no-color run stays byte
// identical to plain text.
//
// A carriage return in provider output is an in-place redraw, not a control
// character to be reported. A provider progress frame such as
// "\rGenerating... 0 chars" is ordinary log content, so it is normalized to a
// line break before sanitization instead of being printed as a replacement rune.
// A line break is used rather than a raw carriage return because a raw 0x0d
// would move the cursor to column zero and let provider data overwrite a trusted
// prompt row.
func filterProviderOutput(content string, policy ColorPolicy) string {
	content = normalizeCarriageReturns(content)
	var output strings.Builder
	writer := &safeWriter{target: &output, keepSGR: policy.Enabled}
	_, _ = writer.Write([]byte(content))
	_ = writer.Flush()
	return output.String()
}

// normalizeCarriageReturns turns every carriage return into a line break. A
// CRLF pair collapses to one break so a Windows-style line ending does not
// produce a blank line, and a standalone carriage return becomes a break so an
// in-place redraw keeps each frame on its own readable line.
func normalizeCarriageReturns(content string) string {
	if !strings.ContainsRune(content, '\r') {
		return content
	}
	content = strings.ReplaceAll(content, "\r\n", "\n")
	return strings.ReplaceAll(content, "\r", "\n")
}
