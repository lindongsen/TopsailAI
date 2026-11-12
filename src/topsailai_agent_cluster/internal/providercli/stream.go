package providercli

import (
	"errors"
	"fmt"
)

// StreamValidator enforces one started frame, ordered records and one end frame.
type StreamValidator struct {
	requestID    string
	started      bool
	ended        bool
	lastSequence int64
}

// NewStreamValidator creates a lifecycle validator for one request.
func NewStreamValidator(requestID string) (*StreamValidator, error) {
	if err := validateIdentifier("request_id", requestID, true); err != nil {
		return nil, err
	}
	return &StreamValidator{requestID: requestID}, nil
}

// Accept validates and records one stream frame.
func (v *StreamValidator) Accept(frame StreamFrame) error {
	if err := frame.Validate(); err != nil {
		return err
	}
	if frame.RequestID != v.requestID {
		return fmt.Errorf("stream request_id %q does not match %q", frame.RequestID, v.requestID)
	}
	if v.ended {
		return errors.New("stream frame received after terminal frame")
	}
	if frame.Sequence != v.lastSequence+1 {
		return fmt.Errorf("stream sequence %d does not follow %d", frame.Sequence, v.lastSequence)
	}
	if !v.started {
		if frame.Type != FrameStarted {
			return errors.New("stream must begin with started frame")
		}
		v.started = true
	} else if frame.Type == FrameStarted {
		return errors.New("stream contains duplicate started frame")
	}
	if frame.Type == FrameEnd {
		v.ended = true
	}
	v.lastSequence = frame.Sequence
	return nil
}

// Finish validates that EOF followed one terminal frame.
func (v *StreamValidator) Finish() error {
	if !v.started {
		return errors.New("stream ended before started frame")
	}
	if !v.ended {
		return errors.New("stream_interrupted: EOF before terminal frame")
	}
	return nil
}
