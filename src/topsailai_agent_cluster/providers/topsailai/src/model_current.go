package main

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

// The closed current-model vocabulary the wire contract declares.
//
// The values are repeated here because this executable is an independent module and
// cannot import the Cluster's protocol package. They are named rather than written
// as bare literals so the three answers stay distinguishable at every call site: a
// profile the session uses now, a profile it does not use, and a profile whose
// status was never observed. The last one is not a negative, and collapsing it into
// one would tell the operator the session uses nothing when the truth is that
// nothing was read.
const (
	modelCurrentYes     = "yes"
	modelCurrentNo      = "no"
	modelCurrentUnknown = "unknown"
)

// providerTargetNotFoundCode is the provider's own code for a control call whose
// session it does not know. It is a provider protocol value, not a Cluster error
// code, and it is distinct from providerSessionNotFoundCode because the two arrive
// on different surfaces: this one comes from a control call, the other from a
// session read.
const providerTargetNotFoundCode = "target_not_found"

// instructionEnvelope is the provider's control-call envelope.
//
// Every registered instruction answers through this one shape, so it is named once
// instead of being redeclared at each call site. Response is a pointer because an
// undelivered call carries no response at all, and that absence is different from a
// response whose status is not ok.
type instructionEnvelope struct {
	OK        bool   `json:"ok"`
	ErrorCode string `json:"error_code"`
	Response  *struct {
		Status string `json:"status"`
		Result string `json:"result"`
	} `json:"response"`
}

// currentModelName reads the model one session is using now.
//
// The provider exposes this as the registered `agent.llm` instruction, which returns
// the live model name as a plain string. The registry read cannot answer this
// question, so the column would otherwise stay empty forever.
//
// The instruction is invoked directly rather than through the operator-configured
// control action catalog, for the same reason model selection is: a first-class
// capability must not depend on someone having also written a catalog entry.
//
// An empty return means the observation was unavailable, and it is never an error.
// The caller reports "unknown" for every profile in that case, which is the honest
// answer: the operator learns that the Endpoint did not observe the current model,
// rather than being told the session uses nothing. Failing the whole catalog read
// would take the menu away because one observation was unavailable.
func (p *provider) currentModelName(ctx context.Context, sessionID string) string {
	args, err := modelInstructionArgs(sessionID, "agent.llm", nil)
	if err != nil {
		return ""
	}
	var envelope instructionEnvelope
	if err := runJSON(ctx, p.runner, args, maxModelBytes, &envelope); err != nil {
		return ""
	}
	if !envelope.OK || envelope.ErrorCode != "" {
		return ""
	}
	if envelope.Response == nil || envelope.Response.Status != "ok" {
		return ""
	}
	return strings.TrimSpace(envelope.Response.Result)
}

// modelCurrentState maps one observed current model name onto the closed
// tri-state vocabulary.
//
// An unobserved name leaves every profile unknown, because "the Endpoint did not
// look" and "the session uses none of these" are different facts. Once a name was
// observed, every profile that does not match it is a definite "no", including the
// case where the observed name is absent from the registry: the provider can report
// a model the registry no longer lists, and the session is then using something
// other than every published profile. That is an observation, not a gap, so it must
// not be reported as unknown.
func modelCurrentState(profileName, currentName string) string {
	if currentName == "" {
		return modelCurrentUnknown
	}
	if profileName == currentName {
		return modelCurrentYes
	}
	return modelCurrentNo
}

// modelInstructionArgs builds the provider argv for one registered instruction.
//
// Every instruction this executable invokes goes through the same provider surface,
// so the argv shape is built in one place. A second copy would let the two call
// sites drift in flag order or in the payload envelope, and the drift would only
// appear as a provider parse failure at runtime.
func modelInstructionArgs(sessionID, instruction string, args []string) ([]string, error) {
	document, err := json.Marshal(map[string]any{
		"instruction": instruction,
		"args":        args,
	})
	if err != nil {
		return nil, fmt.Errorf("encode %s instruction: %w", instruction, err)
	}
	return []string{"runtime", "control", "call_instruction", "-s", sessionID, "-a", string(document), "--json"}, nil
}

// modelInstructionKwargs builds the provider argv for one instruction whose
// parameters are named rather than positional.
//
// The provider forwards `args` as positional arguments and `kwargs` as keyword
// arguments, so the two forms reach the instruction differently. A named
// parameter must use this form: `agent.tokens` reads its `json` flag from the
// named segments, and a positional spelling would depend on the instruction
// accepting extra positional arguments at all.
//
// The argv shape is built here rather than at the call site for the same reason
// as modelInstructionArgs: one spelling, so two call sites cannot drift in flag
// order or in the payload envelope.
func modelInstructionKwargs(sessionID, instruction string, kwargs map[string]string) ([]string, error) {
	document, err := json.Marshal(map[string]any{
		"instruction": instruction,
		"kwargs":      kwargs,
	})
	if err != nil {
		return nil, fmt.Errorf("encode %s instruction: %w", instruction, err)
	}
	return []string{"runtime", "control", "call_instruction", "-s", sessionID, "-a", string(document), "--json"}, nil
}
