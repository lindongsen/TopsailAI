package filetool

import "strings"

// DefaultTruncateLimit is the default message size limit in bytes. Content read
// from a file whose extension is not whitelisted is truncated at this limit.
const DefaultTruncateLimit = 30000

// TruncateSuffix is appended to content that was truncated at the limit.
const TruncateSuffix = " ... (force to truncate)"

// noTruncateExtensions lists the lower-case file extensions whose content is
// returned in full. It mirrors the whitelist of the TopsailAI file tool.
var noTruncateExtensions = []string{
	// flags
	"done", "whole",
	// settings
	"md", "manifest", "conf", "yaml", "yml", "config", "cfg", "rc", "cnf", "xml", "pem", "json",
	"jsonc", "json5", "tpl", "toml", "ini", "inf", "reg", "properties", "env",
	// devlang
	"py", "pyi", "pyw",
	"go",
	"c", "cpp", "cc", "cxx", "h", "hpp", "hxx",
	"sh", "bash", "zsh", "fish", "cmd", "bat", "ps1",
	"ts", "tsx", "cts", "mts", "js", "jsx", "cjs", "mjs",
	"java",
	"cs",
	"rb",
	"php",
	"swift",
	"kt", "kts",
	"rs",
	"scala", "sc",
	"r",
	"pl", "pm",
	"lua",
	"dart",
	"ex", "exs",
	"hs",
	"clj", "cljs",
	"erl", "hrl",
	"m", "mm",
	"groovy",
	"jl",
	"f", "f90", "f95", "f03",
	"asm", "s",
	"vb",
	"fs", "fsx",
	"d",
	"nim",
	"cr",
	"ml", "mli",
	"re", "rei",
	"purs",
	"elm",
	"coffee",
	"lisp", "lsp", "cl",
	"prolog", "plg",
	"sql",
	// web / markup
	"html", "htm", "xhtml",
	"css", "scss", "sass", "less",
	"vue", "svelte",
	"graphql", "gql",
	// data / schema
	"proto", "thrift", "avsc",
	"xsd", "xsl", "xslt", "wsdl", "dtd",
	// build / infra
	"mk", "makefile",
	"gradle", "pom", "sbt", "lein",
	"cabal", "stack",
	"cmake", "cmakelists",
	"bazel", "bzl", "buck", "pants", "ninja", "meson",
	"tf", "tfvars", "hcl", "nomad",
	// docs
	"rst", "adoc", "asciidoc", "mdx", "mkd", "markdown", "org", "textile", "wiki",
	"tex", "latex", "ltx", "bib",
	"pod", "man", "mdoc", "texinfo",
	"groff", "roff", "nroff", "troff",
}

// Options controls truncation behaviour for content reads.
type Options struct {
	// TruncateLimit is the maximum number of bytes returned for a file whose
	// extension is not whitelisted. Values <= 0 fall back to
	// DefaultTruncateLimit.
	TruncateLimit int

	// NoTruncateExtensions overrides the built-in whitelist. Entries are
	// lower-case extensions without a leading dot. The special entries "*"
	// (never truncate) and "!*" (always truncate) are honoured.
	NoTruncateExtensions []string
}

// DefaultOptions returns the built-in truncation behaviour.
func DefaultOptions() Options {
	return Options{TruncateLimit: DefaultTruncateLimit}
}

// limit returns the effective truncation limit.
func (o Options) limit() int {
	if o.TruncateLimit <= 0 {
		return DefaultTruncateLimit
	}
	return o.TruncateLimit
}

// whitelist returns the effective no-truncate extension list.
func (o Options) whitelist() []string {
	if len(o.NoTruncateExtensions) == 0 {
		return noTruncateExtensions
	}
	list := make([]string, 0, len(o.NoTruncateExtensions))
	for _, ext := range o.NoTruncateExtensions {
		list = append(list, strings.ToLower(strings.TrimSpace(ext)))
	}
	for _, ext := range list {
		if ext == "*" {
			return []string{"*"}
		}
	}
	for _, ext := range list {
		if ext == "!*" {
			return nil
		}
	}
	return list
}

// NeedsTruncate reports whether content of the given extension must be
// truncated at the message limit.
func (o Options) NeedsTruncate(ext string) bool {
	list := o.whitelist()
	if len(list) == 0 {
		return true
	}
	ext = strings.ToLower(strings.TrimPrefix(ext, "."))
	for _, candidate := range list {
		if candidate == "*" {
			return false
		}
		if candidate == ext {
			return false
		}
	}
	return true
}

// extensionOf returns the lower-case extension of a path without the dot.
func extensionOf(path string) string {
	lower := strings.ToLower(path)
	idx := strings.LastIndex(lower, ".")
	if idx < 0 {
		return ""
	}
	return lower[idx+1:]
}
