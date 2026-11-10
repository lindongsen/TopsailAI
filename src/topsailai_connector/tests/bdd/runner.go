//go:build bdd

package bdd

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// stepPattern is one registered step: a regular expression and the function that
// runs it. The captured groups are passed to the function as arguments.
type stepPattern struct {
	expression *regexp.Regexp
	run        func(world *world, arguments []string) error
}

// registry holds every registered step. A step is registered once and matched by
// its keyword and its text, so a feature file cannot silently skip a step that no
// definition covers.
type registry struct {
	patterns []stepPattern
}

// given registers a Given step.
func (r *registry) given(expression string, run func(world *world, arguments []string) error) {
	r.patterns = append(r.patterns, stepPattern{expression: regexp.MustCompile("^Given " + expression + "$"), run: run})
}

// when registers a When step.
func (r *registry) when(expression string, run func(world *world, arguments []string) error) {
	r.patterns = append(r.patterns, stepPattern{expression: regexp.MustCompile("^When " + expression + "$"), run: run})
}

// then registers a Then step.
func (r *registry) then(expression string, run func(world *world, arguments []string) error) {
	r.patterns = append(r.patterns, stepPattern{expression: regexp.MustCompile("^Then " + expression + "$"), run: run})
}

// match returns the step that handles a line, or an error naming the line. An
// unmatched step is a failure rather than a skip, because a scenario that
// silently loses a step proves nothing.
func (r *registry) match(line string) (stepPattern, []string, error) {
	for _, pattern := range r.patterns {
		groups := pattern.expression.FindStringSubmatch(line)
		if groups == nil {
			continue
		}
		return pattern, groups[1:], nil
	}
	return stepPattern{}, nil, fmt.Errorf("no step definition matches %q", line)
}

// scenario is one scenario: a name and its steps in order.
type scenario struct {
	name  string
	steps []string
}

// feature is one parsed feature file.
type feature struct {
	name      string
	scenarios []scenario
}

// parseFeature reads a feature file. The parser understands the subset the
// project uses: a Feature line, an optional description under it, Scenario lines
// and step lines. A comment, a blank line and a tag line are ignored.
//
// Two rules keep a typo visible instead of letting it pass as prose:
//
//   - A description is accepted only before the first Scenario. After a Scenario
//     starts, an unrecognised line is an error, because that is where a mistyped
//     step would otherwise be read as text and the scenario would silently lose
//     the step it was meant to run.
//   - "And" inherits the keyword of the step above it, so a step is matched
//     against the definition registered for Given, When or Then. A leading "And"
//     with no step above it is an error rather than a guess.
func parseFeature(path string) (feature, error) {
	handle, err := os.Open(path)
	if err != nil {
		return feature{}, fmt.Errorf("open feature file %q: %w", path, err)
	}
	defer handle.Close()

	parsed := feature{}
	var current *scenario
	lastKeyword := ""

	scanner := bufio.NewScanner(handle)
	lineNumber := 0
	for scanner.Scan() {
		lineNumber++
		line := strings.TrimSpace(scanner.Text())
		switch {
		case line == "":
			continue
		case strings.HasPrefix(line, "#"):
			continue
		case strings.HasPrefix(line, "@"):
			continue
		case strings.HasPrefix(line, "Feature:"):
			parsed.name = strings.TrimSpace(strings.TrimPrefix(line, "Feature:"))
		case strings.HasPrefix(line, "Scenario:"):
			parsed.scenarios = append(parsed.scenarios, scenario{
				name: strings.TrimSpace(strings.TrimPrefix(line, "Scenario:")),
			})
			current = &parsed.scenarios[len(parsed.scenarios)-1]
			lastKeyword = ""
		case strings.HasPrefix(line, "Given "), strings.HasPrefix(line, "When "), strings.HasPrefix(line, "Then "):
			if current == nil {
				return feature{}, fmt.Errorf("%s:%d: step before any scenario", path, lineNumber)
			}
			lastKeyword = keywordOf(line)
			current.steps = append(current.steps, line)
		case strings.HasPrefix(line, "And "):
			if current == nil {
				return feature{}, fmt.Errorf("%s:%d: step before any scenario", path, lineNumber)
			}
			if lastKeyword == "" {
				return feature{}, fmt.Errorf("%s:%d: %q has no step above it to inherit a keyword from", path, lineNumber, line)
			}
			current.steps = append(current.steps, lastKeyword+" "+strings.TrimPrefix(line, "And "))
		default:
			if current == nil {
				continue
			}
			return feature{}, fmt.Errorf("%s:%d: unrecognised line %q", path, lineNumber, line)
		}
	}
	if err := scanner.Err(); err != nil {
		return feature{}, fmt.Errorf("read feature file %q: %w", path, err)
	}
	if parsed.name == "" {
		return feature{}, fmt.Errorf("%s: no Feature line", path)
	}
	if len(parsed.scenarios) == 0 {
		return feature{}, fmt.Errorf("%s: no Scenario line", path)
	}
	return parsed, nil
}

// keywordOf returns the keyword a step line starts with.
func keywordOf(line string) string {
	for _, keyword := range []string{"Given", "When", "Then"} {
		if strings.HasPrefix(line, keyword+" ") {
			return keyword
		}
	}
	return ""
}

// runFeature executes every scenario in a feature file as a subtest, so a failure
// names the scenario rather than the file.
func runFeature(t *testing.T, path string, steps *registry, prepare func(t *testing.T) *world) {
	t.Helper()
	parsed, err := parseFeature(path)
	if err != nil {
		t.Fatalf("%v", err)
	}

	t.Run(parsed.name, func(t *testing.T) {
		for _, current := range parsed.scenarios {
			current := current
			t.Run(current.name, func(t *testing.T) {
				state := prepare(t)
				for _, line := range current.steps {
					pattern, arguments, err := steps.match(line)
					if err != nil {
						t.Fatalf("%v", err)
					}
					if err := pattern.run(state, arguments); err != nil {
						t.Fatalf("%s: %v", line, err)
					}
				}
			})
		}
	})
}

// featureFiles returns every .feature file in a directory, sorted so a run is
// reproducible.
func featureFiles(t *testing.T, directory string) []string {
	t.Helper()
	matches, err := filepath.Glob(filepath.Join(directory, "*.feature"))
	if err != nil {
		t.Fatalf("list feature files in %q: %v", directory, err)
	}
	if len(matches) == 0 {
		t.Fatalf("no .feature file in %q", directory)
	}
	return matches
}
