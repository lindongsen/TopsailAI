package helpdispatch

import (
	"fmt"
	"runtime/debug"
)

// Version returns the one-line version text for a program.
//
// It reads the build information rather than a hand-maintained constant, so the value
// cannot disagree with the binary it describes. The revision is appended when the build
// recorded one, truncated to twelve characters because a full hash is noise in a line a
// person reads.
//
// It lives here rather than in each binary because three copies of one format drift
// apart, and the drift shows up as two binaries reporting the same build differently.
func Version(program string) string {
	version := "(unknown)"
	if info, ok := debug.ReadBuildInfo(); ok {
		if info.Main.Version != "" && info.Main.Version != "(devel)" {
			version = info.Main.Version
		} else {
			version = "devel"
		}
		for _, setting := range info.Settings {
			if setting.Key == "vcs.revision" && setting.Value != "" {
				revision := setting.Value
				if len(revision) > 12 {
					revision = revision[:12]
				}
				version += " (" + revision + ")"
				break
			}
		}
	}
	return fmt.Sprintf("%s %s\n", program, version)
}
