// Package main provides interactive prompt utilities using readline for the ACS CLI terminal.
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"strconv"
	"strings"

	"github.com/chzyer/readline"
)

// ErrCancelled is returned when the user cancels an interactive prompt.
var ErrCancelled = fmt.Errorf("cancelled")

// lineReader abstracts the readline operations used by InteractivePrompt so
// that prompts can be unit-tested without a real terminal.
type lineReader interface {
	SetPrompt(prompt string)
	Clean()
	Readline() (string, error)
	ReadlineWithDefault(defaultValue string) (string, error)
	ReadPassword(label string) (string, error)
}

// readlineLineReader wraps a readline Instance and clears any stale buffer
// before and after each read to prevent input from one prompt leaking into
// the next. This works around chzyer/readline buffer reuse issues when the
// same instance is shared between the command loop and interactive flows.
type readlineLineReader struct {
	rl *readline.Instance
}

func (r *readlineLineReader) SetPrompt(prompt string) { r.rl.SetPrompt(prompt) }
func (r *readlineLineReader) Clean()                  { r.rl.Clean() }
func (r *readlineLineReader) Readline() (string, error) {
	// Defensive: ensure no stale input from a previous prompt remains in the
	// readline buffer before starting a fresh read.
	r.rl.Clean()
	line, err := r.rl.Readline()
	// Defensive: clear the buffer again so the next prompt starts clean.
	r.rl.Clean()
	return line, err
}
func (r *readlineLineReader) ReadlineWithDefault(defaultValue string) (string, error) {
	// Defensive: same cleaning strategy as Readline.
	r.rl.Clean()
	line, err := r.rl.ReadlineWithDefault(defaultValue)
	r.rl.Clean()
	return line, err
}
func (r *readlineLineReader) ReadPassword(label string) (string, error) {
	// Use the existing readline instance's configured terminal/writers rather
	// than creating a new operation with an incomplete Config. Passing a bare
	// Config to ReadPasswordWithConfig leaves Stdout/Stderr/Stdin nil, which
	// causes a nil-pointer panic in RuneBuffer.output when running under tmux.
	buf, err := r.rl.ReadPassword(label + ": ")
	if err != nil {
		return "", ErrCancelled
	}
	return strings.TrimSpace(string(buf)), nil
}

// InteractivePrompt wraps a line reader for step-by-step parameter collection.
type InteractivePrompt struct {
	reader lineReader
}

// NewInteractivePrompt creates a new interactive prompt that reuses the
// provided readline instance. The caller retains ownership of the readline
// instance; this prompt only borrows it while collecting input.
func NewInteractivePrompt(rl *readline.Instance) *InteractivePrompt {
	return &InteractivePrompt{reader: &readlineLineReader{rl: rl}}
}

// newInteractivePromptWithReader is an internal constructor used by tests.
func newInteractivePromptWithReader(reader lineReader) *InteractivePrompt {
	return &InteractivePrompt{reader: reader}
}

// PromptString prompts for a string value. Returns ErrCancelled if input is empty.
func (p *InteractivePrompt) PromptString(label string, required bool) (string, error) {
	for {
		p.reader.Clean()
		p.reader.SetPrompt(label + ": ")
		line, err := p.reader.Readline()
		if err != nil {
			return "", ErrCancelled
		}
		line = strings.TrimSpace(line)
		if line == "" {
			if !required {
				return "", nil
			}
			printWarning("This field is required. Press Ctrl+C to cancel.")
			continue
		}
		return line, nil
	}
}

// PromptStringWithDefault prompts for a string with a default value.
// Pressing Enter without input accepts the default.
func (p *InteractivePrompt) PromptStringWithDefault(label, defaultValue string) (string, error) {
	p.reader.Clean()
	p.reader.SetPrompt(fmt.Sprintf("%s [%s]: ", label, defaultValue))
	line, err := p.reader.ReadlineWithDefault(defaultValue)
	if err != nil {
		return "", ErrCancelled
	}
	line = strings.TrimSpace(line)
	if line == "" {
		return defaultValue, nil
	}
	return line, nil
}

// PromptInt prompts for an integer value.
func (p *InteractivePrompt) PromptInt(label string, required bool) (int, error) {
	for {
		p.reader.Clean()
		p.reader.SetPrompt(label + ": ")
		line, err := p.reader.Readline()
		if err != nil {
			return 0, ErrCancelled
		}
		line = strings.TrimSpace(line)
		if line == "" {
			if !required {
				return 0, nil
			}
			printWarning("This field is required. Press Ctrl+C to cancel.")
			continue
		}
		val, err := strconv.Atoi(line)
		if err != nil {
			printWarning("Please enter a valid integer.")
			continue
		}
		return val, nil
	}
}

// PromptBool prompts for a boolean value (y/n).
// The default value is shown in the prompt label, but the input line is left
// empty so that automation (tmux send-keys, expect scripts, etc.) does not
// have to clear a pre-filled buffer before typing.
func (p *InteractivePrompt) PromptBool(label string, defaultValue bool) (bool, error) {
	defaultStr := "n"
	if defaultValue {
		defaultStr = "y"
	}
	p.reader.Clean()
	p.reader.SetPrompt(fmt.Sprintf("%s [y/n] (default: %s): ", label, defaultStr))
	line, err := p.reader.Readline()
	if err != nil {
		return false, ErrCancelled
	}
	line = strings.ToLower(strings.TrimSpace(line))
	if line == "" {
		return defaultValue, nil
	}
	return line == "y" || line == "yes", nil
}

// PromptChoice prompts the user to choose from a list of options.
func (p *InteractivePrompt) PromptChoice(label string, options []string) (int, string, error) {
	fmt.Println(label + ":")
	for i, opt := range options {
		fmt.Printf("  %d) %s\n", i+1, opt)
	}
	for {
		p.reader.Clean()
		p.reader.SetPrompt("Select (number): ")
		line, err := p.reader.Readline()
		if err != nil {
			return -1, "", ErrCancelled
		}
		line = strings.TrimSpace(line)
		if line == "" {
			printWarning("Please select an option. Press Ctrl+C to cancel.")
			continue
		}
		idx, err := strconv.Atoi(line)
		if err != nil || idx < 1 || idx > len(options) {
			printWarning("Invalid selection. Please enter a valid number.")
			continue
		}
		return idx - 1, options[idx-1], nil
	}
}

// PromptPassword prompts for a password without echoing input to the screen.
// It uses readline's password mode with a '*' mask. Cancellation returns
// ErrCancelled.
func (p *InteractivePrompt) PromptPassword(label string) (string, error) {
	p.reader.Clean()
	line, err := p.reader.ReadPassword(label)
	if err != nil {
		return "", ErrCancelled
	}
	return strings.TrimSpace(line), nil
}

// --- Predefined interactive flows ---

// PromptLogin prompts for login credentials.
func PromptLogin(p *InteractivePrompt) (loginName, loginPassword string, err error) {
	printInfo("Login. Press Ctrl+C or Enter without input to cancel.")
	loginName, err = p.PromptString("Login name", true)
	if err != nil {
		return "", "", err
	}
	loginPassword, err = p.PromptPassword("Password")
	if err != nil {
		return "", "", err
	}
	if loginPassword == "" {
		printWarning("Empty password.")
	}
	return loginName, loginPassword, nil
}
// PromptAuthMethod lets the user choose an authentication method and enter
// the corresponding credential. Supported methods are login-name/password,
// session key, and API key. Cancellation returns ErrCancelled.
func PromptAuthMethod(p *InteractivePrompt) (method, credential string, err error) {
	printInfo("Login. Press Ctrl+C or Enter without input to cancel.")
	_, method, err = p.PromptChoice("Authentication method", []string{
		"login-name/password",
		"session-key",
		"api-key",
	})
	if err != nil {
		return "", "", err
	}

	switch method {
	case "login-name/password":
		loginName, err := p.PromptString("Login name", true)
		if err != nil {
			return "", "", err
		}
		loginPassword, err := p.PromptPassword("Password")
		if err != nil {
			return "", "", err
		}
		return "login-name/password", loginName + "\n" + loginPassword, nil
	case "session-key":
		sessionKey, err := p.PromptString("Session key", true)
		if err != nil {
			return "", "", err
		}
		return "session-key", sessionKey, nil
	case "api-key":
		apiKey, err := p.PromptString("API key", true)
		if err != nil {
			return "", "", err
		}
		return "api-key", apiKey, nil
	}
	return "", "", ErrCancelled
}
// PromptAccountCreate prompts for account creation parameters.
func PromptAccountCreate(p *InteractivePrompt, callerRole string) (req map[string]interface{}, err error) {
	printInfo("Creating a new account. Press Ctrl+C or Enter without input to cancel.")
	req = map[string]interface{}{}

	name, err := p.PromptString("Account name", true)
	if err != nil {
		return nil, err
	}
	req["account_name"] = name

	desc, err := p.PromptString("Account description", false)
	if err != nil {
		return nil, err
	}
	if desc != "" {
		req["account_description"] = desc
	}
	// Only admins can choose a role; managers are forced to user.
	if callerRole == RoleAdmin {
		_, role, err := p.PromptChoice("Role", []string{RoleUser, RoleManager, RoleAdmin})
		if err != nil {
			return nil, err
		}
		req["role"] = role
	} else {
		req["role"] = RoleUser
	}

	loginName, err := p.PromptString("Login name (email)", false)
	if err != nil {
		return nil, err
	}
	if loginName != "" {
		req["login_name"] = loginName
	}

	loginPassword, err := p.PromptPassword("Login password")
	if err != nil {
		return nil, err
	}
	if loginPassword != "" {
		req["login_password"] = loginPassword
	}

	email, err := p.PromptString("Email", false)
	if err != nil {
		return nil, err
	}
	if email != "" {
		req["email"] = email
	}

	externalID, err := p.PromptString("External ID", false)
	if err != nil {
		return nil, err
	}
	if externalID != "" {
		req["external_id"] = externalID
	}

	authProvider, err := p.PromptString("Auth provider", false)
	if err != nil {
		return nil, err
	}
	if authProvider != "" {
		req["auth_provider"] = authProvider
	}

	avatarURL, err := p.PromptString("Avatar URL", false)
	if err != nil {
		return nil, err
	}
	if avatarURL != "" {
		req["avatar_url"] = avatarURL
	}

	return req, nil
}

// PromptAccountUpdate prompts for account update parameters.
func PromptAccountUpdate(p *InteractivePrompt) (req map[string]interface{}, err error) {
	printInfo("Updating account. Press Ctrl+C or Enter without input to cancel.")
	req = map[string]interface{}{}

	name, err := p.PromptString("New account name (leave empty to keep current)", false)
	if err != nil {
		return nil, err
	}
	if name != "" {
		req["account_name"] = name
	}

	desc, err := p.PromptString("New account description (leave empty to keep current)", false)
	if err != nil {
		return nil, err
	}
	if desc != "" {
		req["account_description"] = desc
	}

	avatarURL, err := p.PromptString("New avatar URL (leave empty to keep current)", false)
	if err != nil {
		return nil, err
	}
	if avatarURL != "" {
		req["avatar_url"] = avatarURL
	}

	return req, nil
}

// PromptPasswordChange prompts for password change parameters.
func PromptPasswordChange(p *InteractivePrompt, requireOld bool) (oldPassword, newPassword string, err error) {
	printInfo("Changing password. Press Ctrl+C or Enter without input to cancel.")
	if requireOld {
		oldPassword, err = p.PromptPassword("Old password")
		if err != nil {
			return "", "", err
		}
	}
	newPassword, err = p.PromptPassword("New password")
	if err != nil {
		return "", "", err
	}
	if newPassword == "" {
		return "", "", fmt.Errorf("new password cannot be empty")
	}
	confirm, err := p.PromptPassword("Confirm new password")
	if err != nil {
		return "", "", err
	}
	if confirm != newPassword {
		return "", "", fmt.Errorf("passwords do not match")
	}
	return oldPassword, newPassword, nil
}

// PromptAPIKeyCreate prompts for API key creation parameters.
func PromptAPIKeyCreate(p *InteractivePrompt, callerRole, callerID string) (accountID, name, role string, err error) {
	printInfo("Creating an API key. Press Ctrl+C or Enter without input to cancel.")

	accountID, err = p.PromptStringWithDefault("Account ID", callerID)
	if err != nil {
		return "", "", "", err
	}

	name, err = p.PromptString("API key name", true)
	if err != nil {
		return "", "", "", err
	}

	if callerRole == RoleAdmin {
		_, role, err = p.PromptChoice("Role", []string{RoleUser, RoleManager, RoleAdmin})
		if err != nil {
			return "", "", "", err
		}
	} else {
		role = RoleUser
	}

	return accountID, name, role, nil
}

// PromptAPIKeyList prompts for API key list parameters.
func PromptAPIKeyList(p *InteractivePrompt, defaultAccountID string) (accountID, status string, err error) {
	printInfo("Listing API keys. Press Ctrl+C or Enter without input to cancel.")

	accountID, err = p.PromptStringWithDefault("Account ID", defaultAccountID)
	if err != nil {
		return "", "", err
	}

	status, err = p.PromptString("Status filter (active/inactive, leave empty for all)", false)
	if err != nil {
		return "", "", err
	}
	if status != "" && status != "active" && status != "inactive" {
		return "", "", fmt.Errorf("invalid status filter: %s", status)
	}

	return accountID, status, nil
}

// PromptAPIKeyDelete prompts for API key deletion parameters.
func PromptAPIKeyDelete(p *InteractivePrompt, defaultAccountID string) (accountID, apiKeyID string, err error) {
	printInfo("Deleting an API key. Press Ctrl+C or Enter without input to cancel.")
	accountID, err = p.PromptStringWithDefault("Account ID", defaultAccountID)
	if err != nil {
		return "", "", err
	}
	apiKeyID, err = p.PromptString("API Key ID", true)
	if err != nil {
		return "", "", err
	}
	return accountID, apiKeyID, nil
}

// PromptGroupCreate prompts for group creation parameters.
func PromptGroupCreate(p *InteractivePrompt) (name, context, key string, err error) {
	printInfo("Creating a new group. Press Ctrl+C or Enter without input to cancel.")
	name, err = p.PromptString("Group name", true)
	if err != nil {
		return "", "", "", err
	}
	context, err = p.PromptString("Group context (description)", false)
	if err != nil {
		return "", "", "", err
	}
	key, err = p.PromptPassword("Group key (leave empty for public)")
	if err != nil {
		return "", "", "", err
	}
	return name, context, key, nil
}

// PromptGroupUpdate prompts for group update parameters.
func PromptGroupUpdate(p *InteractivePrompt) (name, context, key string, err error) {
	printInfo("Updating group. Press Ctrl+C or Enter without input to cancel.")
	name, err = p.PromptString("New group name (leave empty to keep current)", false)
	if err != nil {
		return "", "", "", err
	}
	context, err = p.PromptString("New group context (leave empty to keep current)", false)
	if err != nil {
		return "", "", "", err
	}
	key, err = p.PromptPassword("New group key (leave empty to keep current)")
	if err != nil {
		return "", "", "", err
	}
	return name, context, key, nil
}

// PromptMemberAdd prompts for member addition parameters.
func PromptMemberAdd(p *InteractivePrompt) (memberID, memberName, memberDesc, memberType string, memberInterface map[string]interface{}, err error) {
	printInfo("Adding a member. Press Ctrl+C or Enter without input to cancel.")
	memberID, err = p.PromptString("Member ID", true)
	if err != nil {
		return "", "", "", "", nil, err
	}
	memberName, err = p.PromptString("Member name", true)
	if err != nil {
		return "", "", "", "", nil, err
	}
	memberDesc, err = p.PromptString("Member description", false)
	if err != nil {
		return "", "", "", "", nil, err
	}
	_, memberType, err = p.PromptChoice("Member type", []string{"user", "manager-agent", "worker-agent"})
	if err != nil {
		return "", "", "", "", nil, err
	}
	// Member interface is optional JSON. Accept either a JSON object or a
	// JSON-encoded string; leave empty to omit it.
	ifaceRaw, err := p.PromptString("Member interface JSON (optional)", false)
	if err != nil {
		return "", "", "", "", nil, err
	}
	if ifaceRaw != "" {
		memberInterface, err = parseMemberInterface(ifaceRaw)
		if err != nil {
			return "", "", "", "", nil, err
		}
	}
	return memberID, memberName, memberDesc, memberType, memberInterface, nil
}

// parseMemberInterface parses a member_interface value that may be supplied as
// a JSON object or a JSON-encoded string. It returns a map suitable for the
// AddMember API payload.
func parseMemberInterface(raw string) (map[string]interface{}, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil, nil
	}
	// If the input is a JSON string (starts and ends with quotes), unwrap it.
	if len(raw) >= 2 && raw[0] == '"' && raw[len(raw)-1] == '"' {
		var s string
		if err := json.Unmarshal([]byte(raw), &s); err != nil {
			return nil, fmt.Errorf("invalid JSON string for member_interface: %w", err)
		}
		raw = strings.TrimSpace(s)
	}
	if raw == "" {
		return nil, nil
	}
	var v map[string]interface{}
	if err := json.Unmarshal([]byte(raw), &v); err != nil {
		return nil, fmt.Errorf("member_interface is not valid JSON object: %w", err)
	}
	return v, nil
}

// PromptMemberUpdate prompts for member update parameters.
func PromptMemberUpdate(p *InteractivePrompt) (memberName, memberDesc, memberStatus string, err error) {
	printInfo("Updating member. Press Ctrl+C or Enter without input to cancel.")
	memberName, err = p.PromptString("New member name (leave empty to keep current)", false)
	if err != nil {
		return "", "", "", err
	}
	memberDesc, err = p.PromptString("New member description (leave empty to keep current)", false)
	if err != nil {
		return "", "", "", err
	}
	_, memberStatus, err = p.PromptChoice("New member status", []string{"online", "offline", "idle", "processing"})
	if err != nil {
		return "", "", "", err
	}
	return memberName, memberDesc, memberStatus, nil
}

// PromptMessageEdit prompts for message edit parameters.
func PromptMessageEdit(p *InteractivePrompt) (text string, err error) {
	printInfo("Editing message. Press Ctrl+C or Enter without input to cancel.")
	text, err = p.PromptString("New message text", true)
	if err != nil {
		return "", err
	}
	return text, nil
}

// Compile-time check that mockLineReader implements lineReader.
var _ lineReader = (*mockLineReader)(nil)

// mockLineReader is a test double that returns a scripted sequence of lines.
type mockLineReader struct {
	lines   []string
	idx     int
	prompts []string
}

func (m *mockLineReader) SetPrompt(prompt string) { m.prompts = append(m.prompts, prompt) }
func (m *mockLineReader) Clean()                  {}
func (m *mockLineReader) Readline() (string, error) {
	if m.idx >= len(m.lines) {
		return "", io.EOF
	}
	line := m.lines[m.idx]
	m.idx++
	return line, nil
}
func (m *mockLineReader) ReadlineWithDefault(defaultValue string) (string, error) {
	return m.Readline()
}
func (m *mockLineReader) ReadPassword(label string) (string, error) {
	m.SetPrompt(label + ": ")
	return m.Readline()
}
