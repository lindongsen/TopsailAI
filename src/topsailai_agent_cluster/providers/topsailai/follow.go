package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"time"
)

const (
	followDefaultRecordBytes = 64 << 10
	followMaxRecordBytes     = 1 << 20
	followTerminalGrace      = 250 * time.Millisecond
)

type followRecord struct {
	Line      string
	Truncated bool
}

type streamCommandRunner interface {
	Follow(context.Context, []string, int, func(followRecord) error) error
}

// followOutput emits one strict Provider CLI JSONL lifecycle.
func (p *provider) followOutput(ctx context.Context, request request, writer io.Writer) error {
	followCtx, cancel := followRequestContext(ctx, request.DeadlineAtMS, p.now())
	defer cancel()
	encoder := json.NewEncoder(writer)
	encoder.SetEscapeHTML(false)
	sequence := int64(1)
	if err := encoder.Encode(streamFrame{version: currentVersion(), RequestID: request.RequestID, Type: frameStarted, Sequence: sequence}); err != nil {
		return fmt.Errorf("encode follow start: %w", err)
	}
	sequence++

	endError := p.runFollow(followCtx, request, func(record followRecord) error {
		payload, err := json.Marshal(struct {
			Lines []string `json:"lines"`
		}{Lines: []string{record.Line}})
		if err != nil {
			return fmt.Errorf("encode follow record: %w", err)
		}
		frame := streamFrame{
			version:      currentVersion(),
			RequestID:    request.RequestID,
			Type:         frameRecord,
			Sequence:     sequence,
			ObservedAtMS: p.now().UnixMilli(),
			Record:       payload,
			Truncated:    record.Truncated,
		}
		if err := encoder.Encode(frame); err != nil {
			return fmt.Errorf("write follow record: %w", err)
		}
		sequence++
		return nil
	})

	terminal := streamFrame{version: currentVersion(), RequestID: request.RequestID, Type: frameEnd, Sequence: sequence}
	if endError != nil {
		terminal.Error = streamError(endError)
	}
	if err := encoder.Encode(terminal); err != nil {
		return fmt.Errorf("encode follow end: %w", err)
	}
	return nil
}

func followRequestContext(parent context.Context, deadlineAtMS int64, now time.Time) (context.Context, context.CancelFunc) {
	remaining := time.UnixMilli(deadlineAtMS).Sub(now) - followTerminalGrace
	if remaining <= 0 {
		remaining = time.Nanosecond
	}
	return context.WithTimeout(parent, remaining)
}

func (p *provider) runFollow(ctx context.Context, request request, emit func(followRecord) error) error {
	var payload outputPayload
	if err := decodeStrict(request.Payload, &payload); err != nil || payload.MaxBytes < 0 || payload.MaxBytes > followMaxRecordBytes || payload.MaxLines < 0 || payload.MaxLines > 10000 {
		return fmt.Errorf("%w: invalid output payload", errInvalidRequest)
	}
	resolved, err := p.resolveWorkspaceTarget(ctx, request.Target)
	if err != nil {
		return err
	}
	runner, ok := p.runner.(streamCommandRunner)
	if !ok {
		return fmt.Errorf("%w: follow runner is unavailable", errUnsupported)
	}
	lines := payload.MaxLines
	if lines == 0 {
		lines = 20
	}
	limit := payload.MaxBytes
	if limit == 0 {
		limit = followDefaultRecordBytes
	}
	return runner.Follow(ctx, runtimeLogArgs(resolved, lines, true), limit, emit)
}

func streamError(err error) *providerError {
	code := errorCode(err)
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		code = "cancelled"
	}
	return &providerError{
		Code:            code,
		Message:         boundedString(err.Error(), 4096),
		Retryable:       false,
		EffectCertainty: effectNotApplied,
	}
}

// scanFollowLines emits complete lines and a final unterminated line. Oversized
// lines are truncated on a UTF-8 boundary while the stream continues.
func scanFollowLines(reader io.Reader, limit int, emit func(followRecord) error) error {
	buffered := bufio.NewReaderSize(reader, 64<<10)
	for {
		record, ok, err := readFollowRecord(buffered, limit)
		if ok {
			if emitErr := emit(record); emitErr != nil {
				return emitErr
			}
		}
		if err != nil {
			if errors.Is(err, io.EOF) {
				return nil
			}
			return fmt.Errorf("read follow output: %w", err)
		}
	}
}

func readFollowRecord(reader *bufio.Reader, limit int) (followRecord, bool, error) {
	if limit <= 0 {
		limit = followDefaultRecordBytes
	}
	if limit > followMaxRecordBytes {
		limit = followMaxRecordBytes
	}
	var record followRecord
	var collected []byte
	discarding := false
	for {
		piece, err := reader.ReadSlice('\n')
		if len(piece) > 0 {
			terminated := piece[len(piece)-1] == '\n'
			if terminated {
				piece = piece[:len(piece)-1]
			}
			if !discarding {
				room := limit - len(collected)
				if len(piece) <= room {
					collected = append(collected, piece...)
				} else {
					collected = append(collected, []byte(boundedString(string(piece), room))...)
					record.Truncated = true
					discarding = true
				}
			}
			if terminated {
				record.Line = string(collected)
				return record, true, nil
			}
		}
		if err != nil {
			if errors.Is(err, bufio.ErrBufferFull) {
				continue
			}
			if errors.Is(err, io.EOF) {
				if len(collected) > 0 || record.Truncated {
					record.Line = string(collected)
					return record, true, nil
				}
				return record, false, io.EOF
			}
			return record, false, err
		}
	}
}

func followEnvironment(executable string, base []string) []string {
	environment := make([]string, 0, len(base)+1)
	for _, entry := range base {
		if strings.HasPrefix(entry, "PYTHONUNBUFFERED=") {
			continue
		}
		environment = append(environment, entry)
	}
	environment = append(environment, "PYTHONUNBUFFERED=1")
	return providerEnvironment(executable, environment)
}
