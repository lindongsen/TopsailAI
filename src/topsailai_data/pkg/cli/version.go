// Version reporting for the topsailai-data CLI.
//
// The version query is answered before configuration loading and adapter
// initialization, so it works even when the store configuration is broken or
// the data root is unavailable.
package cli

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/spf13/pflag"
	"github.com/topsailai/topsailai_data/pkg/manager"
	"github.com/topsailai/topsailai_data/pkg/version"
	"gopkg.in/yaml.v3"
)

// versionFlagNames lists the top-level flag spellings that request the version.
var versionFlagNames = map[string]bool{
	"-v":        true,
	"--version": true,
	"-version":  true,
}

// VersionRequest reports whether args ask for the CLI version instead of a data
// command. It accepts the "version" command and the top-level flag spellings.
func VersionRequest(args []string) bool {
	if len(args) == 0 {
		return false
	}
	return args[0] == "version" || versionFlagNames[args[0]]
}

// PrintVersion writes the build metadata report for a version request. args is
// the complete argument list, so the leading command or flag is skipped before
// the remaining flags are parsed.
func PrintVersion(w io.Writer, args []string) error {
	fs := pflag.NewFlagSet("version", pflag.ContinueOnError)
	fs.SetOutput(os.Stderr)
	format := fs.String("format", "text", "output format: text, yaml, or json")
	if len(args) > 0 {
		args = args[1:]
	}
	if err := fs.Parse(args); err != nil {
		return err
	}
	if err := requireArgs(fs.Args(), 0, 0); err != nil {
		return fmt.Errorf("version: %w", err)
	}

	info := version.Get()
	switch *format {
	case "text":
		fmt.Fprintln(w, info.Line())
	case "json":
		data, err := json.MarshalIndent(info, "", "  ")
		if err != nil {
			return fmt.Errorf("version: encode json: %w", err)
		}
		fmt.Fprintln(w, string(data))
	case "yaml":
		data, err := yaml.Marshal(info)
		if err != nil {
			return fmt.Errorf("version: encode yaml: %w", err)
		}
		fmt.Fprint(w, string(data))
	default:
		return fmt.Errorf("version: invalid --format %q: must be text, yaml, or json", *format)
	}
	return nil
}

// runVersion implements the "version" command. The manager is unused because a
// version query must not depend on the store configuration.
func runVersion(_ context.Context, _ *manager.Manager, args []string) error {
	return PrintVersion(os.Stdout, append([]string{"version"}, args...))
}
