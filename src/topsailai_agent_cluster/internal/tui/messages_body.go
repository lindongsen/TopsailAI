package tui

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"unicode/utf8"
)

// Structured-body rendering constants.
//
// The depth bound exists so a deeply nested body cannot produce unbounded
// indentation, which would push the text off the right edge of the terminal and
// make it unreadable in a different way than raw JSON.
const (
	// messagesBodyMaxDepth is the deepest nesting that is still indented. A value
	// beyond it is printed inline, so the body stays bounded.
	messagesBodyMaxDepth = 6
	// messagesBodyIndent is one nesting level.
	messagesBodyIndent = "  "
	// messagesBodyInlineLimit is the rune count above which a string value is
	// placed on its own indented block instead of after its key. A long value on
	// the same line as its key would wrap at the terminal edge and lose the
	// association between the two.
	messagesBodyInlineLimit = 60
	// messagesBodyBullet marks one scalar list item.
	messagesBodyBullet = "- "
)

// renderStructuredBody converts a message body that is still a JSON object or
// array into readable text.
//
// The cluster is the abstraction layer, so a structured body is rendered for a
// human instead of being forwarded as JSON. The rule is deliberately generic: it
// never names a provider field, because provider vocabulary belongs to the adapter
// and must not appear in the renderer. A body that is not valid JSON, or that
// decodes to a bare scalar, is returned unchanged, so nothing is ever lost.
//
// The rendering is applied after the adapter has already unwrapped its own step
// records. A body that reaches this function is therefore either a structure the
// adapter does not model, or a structure it could not safely unwrap. Both cases
// are better shown as readable text than as braces and quotes.
func renderStructuredBody(content string) string {
	trimmed := strings.TrimSpace(content)
	if trimmed == "" {
		return content
	}
	// The prefilter avoids a decode attempt for ordinary prose, which is the
	// common case and must stay cheap.
	if !strings.HasPrefix(trimmed, "{") && !strings.HasPrefix(trimmed, "[") {
		return content
	}
	var decoded any
	if err := json.Unmarshal([]byte(trimmed), &decoded); err != nil {
		return content
	}
	switch value := decoded.(type) {
	case map[string]any:
		rendered := renderStructuredObject(value, 0)
		if rendered == "" {
			return content
		}
		return rendered
	case []any:
		rendered := renderStructuredArray(value, 0)
		if rendered == "" {
			return content
		}
		return rendered
	default:
		// A bare scalar carries no structure to improve on, so the original text
		// is kept rather than replaced by a re-encoded form.
		return content
	}
}

// renderStructuredObject renders one JSON object as "key: value" lines.
//
// Keys are sorted so the same body renders identically on every read. A nested
// object or array is indented under its key, and a long or multi-line string is
// placed on its own indented block so the key stays adjacent to the text it
// labels.
func renderStructuredObject(object map[string]any, depth int) string {
	if len(object) == 0 {
		return ""
	}
	keys := make([]string, 0, len(object))
	for key := range object {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	indent := strings.Repeat(messagesBodyIndent, depth)
	lines := make([]string, 0, len(keys))
	for _, key := range keys {
		lines = append(lines, renderObjectEntry(key, object[key], depth, indent)...)
	}
	return strings.Join(lines, "\n")
}

// renderObjectEntry renders one key and its value as one or more lines.
//
// It returns a slice rather than a string because a nested value contributes
// several lines, and joining them here would make the caller responsible for the
// newline placement of every branch.
func renderObjectEntry(key string, value any, depth int, indent string) []string {
	prefix := indent + key + ":"
	switch typed := value.(type) {
	case map[string]any:
		if depth+1 >= messagesBodyMaxDepth {
			return []string{prefix + " " + renderInlineValue(typed)}
		}
		nested := renderStructuredObject(typed, depth+1)
		if nested == "" {
			return []string{prefix + " {}"}
		}
		return append([]string{prefix}, strings.Split(nested, "\n")...)
	case []any:
		if depth+1 >= messagesBodyMaxDepth {
			return []string{prefix + " " + renderInlineValue(typed)}
		}
		nested := renderStructuredArray(typed, depth+1)
		if nested == "" {
			return []string{prefix + " []"}
		}
		return append([]string{prefix}, strings.Split(nested, "\n")...)
	case string:
		if needsOwnBlock(typed) {
			return append([]string{prefix}, strings.Split(indentBlock(typed, depth+1), "\n")...)
		}
		return []string{prefix + " " + typed}
	case nil:
		return []string{prefix + " null"}
	default:
		return []string{prefix + " " + fmt.Sprint(typed)}
	}
}

// renderStructuredArray renders one JSON array.
//
// A list of scalars becomes bullets, because a bulleted list is read faster than
// numbered blocks and the items have no identity of their own. A list that
// contains any object becomes numbered blocks, because each block is a record and
// the number is what lets an operator refer to one of them.
func renderStructuredArray(items []any, depth int) string {
	if len(items) == 0 {
		return ""
	}
	indent := strings.Repeat(messagesBodyIndent, depth)
	hasObject := false
	for _, item := range items {
		switch item.(type) {
		case map[string]any, []any:
			hasObject = true
		}
	}
	blocks := make([]string, 0, len(items))
	for index, item := range items {
		marker := fmt.Sprintf("[%d]", index+1)
		switch typed := item.(type) {
		case map[string]any:
			if depth+1 >= messagesBodyMaxDepth {
				blocks = append(blocks, indent+marker+" "+renderInlineValue(typed))
				continue
			}
			nested := renderStructuredObject(typed, depth+1)
			if nested == "" {
				blocks = append(blocks, indent+marker+" {}")
				continue
			}
			blocks = append(blocks, indent+marker+"\n"+nested)
		case []any:
			if depth+1 >= messagesBodyMaxDepth {
				blocks = append(blocks, indent+marker+" "+renderInlineValue(typed))
				continue
			}
			nested := renderStructuredArray(typed, depth+1)
			if nested == "" {
				blocks = append(blocks, indent+marker+" []")
				continue
			}
			blocks = append(blocks, indent+marker+"\n"+nested)
		case string:
			if hasObject {
				// A mixed list is numbered so the scalar keeps a position among
				// the records instead of looking like a stray line.
				blocks = append(blocks, indent+marker+" "+typed)
				continue
			}
			blocks = append(blocks, indent+messagesBodyBullet+typed)
		case nil:
			blocks = append(blocks, indent+messagesBodyBullet+"null")
		default:
			blocks = append(blocks, indent+messagesBodyBullet+fmt.Sprint(typed))
		}
	}
	// Records are separated by a blank line so each numbered block reads as one
	// unit. Bullets are not, because a blank line between single-line items only
	// makes the list taller.
	separator := "\n"
	if hasObject {
		separator = "\n\n"
	}
	return strings.Join(blocks, separator)
}

// renderInlineValue encodes a value that is too deep to indent.
//
// The encoding is the compact JSON form, which is the only representation that
// keeps every field. It is used only past the depth bound, where the alternative
// is unbounded indentation rather than a readable block.
func renderInlineValue(value any) string {
	encoded, err := json.Marshal(value)
	if err != nil {
		return fmt.Sprint(value)
	}
	return string(encoded)
}

// needsOwnBlock reports whether a string value is too long or too tall to sit on
// the same line as its key.
func needsOwnBlock(value string) bool {
	if strings.Contains(value, "\n") {
		return true
	}
	return utf8.RuneCountInString(value) > messagesBodyInlineLimit
}

// indentBlock indents every line of a multi-line value by one nesting level.
//
// The value is indented line by line rather than as one string, because a
// multi-line value would otherwise have its later lines start at column zero and
// read as if they belonged to the enclosing object.
func indentBlock(value string, depth int) string {
	indent := strings.Repeat(messagesBodyIndent, depth)
	lines := strings.Split(strings.TrimRight(value, "\n"), "\n")
	var builder strings.Builder
	for index, line := range lines {
		if index > 0 {
			builder.WriteString("\n")
		}
		if line == "" {
			continue
		}
		builder.WriteString(indent)
		builder.WriteString(line)
	}
	return builder.String()
}
