package providercli

import (
	"encoding/json"
	"fmt"
)

func validateRequestPresence(data []byte) error {
	root, err := decodeRawObject(data, "provider request")
	if err != nil {
		return err
	}
	if err := requireFields(root, "provider request", "protocol", "major", "minor", "request_id", "function", "adapter_id", "deadline_at_ms", "budget", "payload"); err != nil {
		return err
	}
	budget, err := decodeNestedObject(root, "budget", "provider request budget")
	if err != nil {
		return err
	}
	if err := requireFields(budget, "provider request budget", "max_stdout_bytes", "max_stderr_bytes", "max_records"); err != nil {
		return err
	}
	var function string
	if err := json.Unmarshal(root["function"], &function); err != nil {
		return fmt.Errorf("decode provider request function: %w", err)
	}
	switch function {
	case FunctionExecute:
		if err := requireFields(root, "execute request", "invocation_id", "target", "operation"); err != nil {
			return err
		}
		return forbidFields(root, "execute request", "query")
	case FunctionQuery:
		if err := requireFields(root, "query request", "query"); err != nil {
			return err
		}
		return forbidFields(root, "query request", "operation", "invocation_id")
	case FunctionInspect, FunctionReadOutput, FunctionFollowOutput:
		if err := requireFields(root, function+" request", "target"); err != nil {
			return err
		}
		return forbidFields(root, function+" request", "operation", "query", "invocation_id")
	case FunctionQueryCommand:
		if err := requireFields(root, "query_command request", "invocation_id"); err != nil {
			return err
		}
		return forbidFields(root, "query_command request", "operation", "query")
	case FunctionDescribe, FunctionDiscover, FunctionWatch:
		return forbidFields(root, function+" request", "operation", "query", "invocation_id", "target")
	default:
		return nil
	}
}

func validateResponsePresence(data []byte) error {
	root, err := decodeRawObject(data, "provider response")
	if err != nil {
		return err
	}
	if err := requireFields(root, "provider response", "protocol", "major", "minor", "request_id", "ok"); err != nil {
		return err
	}
	var ok bool
	if err := json.Unmarshal(root["ok"], &ok); err != nil {
		return fmt.Errorf("decode provider response ok: %w", err)
	}
	if !ok {
		errorDocument, err := decodeNestedObject(root, "error", "provider error")
		if err != nil {
			return err
		}
		return requireFields(errorDocument, "provider error", "code", "message", "retryable", "effect_certainty")
	}
	return validateSuccessPresence(root)
}

func validateSuccessPresence(root map[string]json.RawMessage) error {
	switch {
	case root["descriptor"] != nil:
		return validateDescriptorPresence(root)
	case root["discovery"] != nil:
		discovery, err := decodeNestedObject(root, "discovery", "discovery result")
		if err != nil {
			return err
		}
		return requireFields(discovery, "discovery result", "observations", "complete")
	case root["inspection"] != nil:
		inspection, err := decodeNestedObject(root, "inspection", "inspection result")
		if err != nil {
			return err
		}
		return requireFields(inspection, "inspection result", "found", "live")
	case root["result"] != nil:
		result, err := decodeNestedObject(root, "result", "operation result")
		if err != nil {
			return err
		}
		if err := requireFields(result, "operation result", "delivery_boundary", "effect_certainty", "provider_outcome", "provider_response_truncated"); err != nil {
			return err
		}
		return validatePositiveOptionalIntegers(result, "operation result", "started_at_ms", "finished_at_ms")
	case root["output"] != nil:
		output, err := decodeNestedObject(root, "output", "output snapshot")
		if err != nil {
			return err
		}
		return requireFields(output, "output snapshot", "observed_at_ms", "content", "truncated", "complete")
	default:
		return nil
	}
}

func validateDescriptorPresence(root map[string]json.RawMessage) error {
	descriptor, err := decodeNestedObject(root, "descriptor", "provider descriptor")
	if err != nil {
		return err
	}
	if err := requireFields(descriptor, "provider descriptor", "provider_type", "provider_version", "descriptor_revision", "protocol_range", "functions", "operations", "queries", "control_actions", "limits", "concurrency"); err != nil {
		return err
	}
	protocolRange, err := decodeNestedObject(descriptor, "protocol_range", "provider protocol range")
	if err != nil {
		return err
	}
	if err := requireFields(protocolRange, "provider protocol range", "protocol", "major", "minimum_minor", "maximum_minor"); err != nil {
		return err
	}
	limits, err := decodeNestedObject(descriptor, "limits", "provider limits")
	if err != nil {
		return err
	}
	if err := requireFields(limits, "provider limits", "max_stdout_bytes", "max_stderr_bytes", "max_records"); err != nil {
		return err
	}
	concurrency, err := decodeNestedObject(descriptor, "concurrency", "provider concurrency")
	if err != nil {
		return err
	}
	return requireFields(concurrency, "provider concurrency", "total", "discovery", "mutation", "follow")
}

func validateStreamFramePresence(data []byte) error {
	root, err := decodeRawObject(data, "provider stream frame")
	if err != nil {
		return err
	}
	if err := requireFields(root, "provider stream frame", "protocol", "major", "minor", "request_id", "type", "sequence"); err != nil {
		return err
	}
	var frameType string
	if err := json.Unmarshal(root["type"], &frameType); err != nil {
		return fmt.Errorf("decode provider stream frame type: %w", err)
	}
	switch frameType {
	case FrameStarted:
		return forbidFields(root, "started frame", "observed_at_ms", "record", "truncated", "error")
	case FrameRecord:
		if err := requireFields(root, "record frame", "observed_at_ms", "record"); err != nil {
			return err
		}
		return forbidFields(root, "record frame", "error")
	case FrameEnd:
		if err := forbidFields(root, "end frame", "observed_at_ms", "record", "truncated"); err != nil {
			return err
		}
		if root["error"] == nil {
			return nil
		}
		errorDocument, err := decodeNestedObject(root, "error", "provider error")
		if err != nil {
			return err
		}
		return requireFields(errorDocument, "provider error", "code", "message", "retryable", "effect_certainty")
	default:
		return nil
	}
}

func decodeRawObject(data []byte, label string) (map[string]json.RawMessage, error) {
	var object map[string]json.RawMessage
	if err := json.Unmarshal(data, &object); err != nil {
		return nil, fmt.Errorf("decode %s fields: %w", label, err)
	}
	if object == nil {
		return nil, fmt.Errorf("%s must be an object", label)
	}
	return object, nil
}

func decodeNestedObject(root map[string]json.RawMessage, field, label string) (map[string]json.RawMessage, error) {
	raw := root[field]
	if raw == nil {
		return nil, fmt.Errorf("%s is required", field)
	}
	return decodeRawObject(raw, label)
}

func requireFields(object map[string]json.RawMessage, label string, fields ...string) error {
	for _, field := range fields {
		if object[field] == nil {
			return fmt.Errorf("%s field %s is required", label, field)
		}
	}
	return nil
}

func validatePositiveOptionalIntegers(object map[string]json.RawMessage, label string, fields ...string) error {
	for _, field := range fields {
		raw := object[field]
		if raw == nil {
			continue
		}
		var value int64
		if err := json.Unmarshal(raw, &value); err != nil {
			return fmt.Errorf("decode %s %s: %w", label, field, err)
		}
		if value < 1 {
			return fmt.Errorf("%s %s must be positive when present", label, field)
		}
	}
	return nil
}

func forbidFields(object map[string]json.RawMessage, label string, fields ...string) error {
	for _, field := range fields {
		if object[field] != nil {
			return fmt.Errorf("%s must not contain %s", label, field)
		}
	}
	return nil
}
