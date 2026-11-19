package cli

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"topsailai_connector/internal/protocol"
)

// chunkBytes is the largest payload one `file.read` request can return.
//
// It mirrors the Node's own response cap. The CLI asks for exactly this much so a
// whole-file read makes the fewest requests the Node will allow, and it never asks
// for more because a larger request would be silently cut to the cap and the loop
// would then depend on a number it did not choose.
const chunkBytes = 256 * 1024

// stdoutDestination is the Output value that means "write to stdout".
const stdoutDestination = "-"

// readChunk is the documented `file.read` payload.
type readChunk struct {
	Content   []byte `json:"content"`
	Size      int64  `json:"size"`
	Truncated bool   `json:"truncated"`
}

// fetchWholeFile reads a whole file, or a requested byte range of it, by repeating
// `file.read` until the Node reports that it reached end of file.
//
// The loop is driven by the response and never by a hardcoded step size, so a change
// to the Node's cap does not require a change here. Three conditions stop it, and each
// covers a case the others miss:
//
//   - `truncated` is false: the Node reached end of file, so there is nothing left.
//     This is the ordinary stop, and it is also what stops an empty file, whose first
//     response is zero bytes with `truncated` false.
//   - `size` is zero: a response that claims more remains but delivered nothing. The
//     Node does not produce that today, but a loop that trusted `truncated` alone would
//     spin forever on it, and a spin is a hang rather than an error. Measured: removing
//     this condition leaves every other test green, so it guards a contradictory
//     response rather than the empty file.
//   - the caller's `--length` budget is spent.
//
// `truncated` is trusted only in the safe direction. A false value always means the
// read reached end of file, so stopping on it never drops data. A true value is
// trustworthy too, but the loop is written so it does not depend on that: a Node
// older than the fix in `a5b580e3` reported truncation for a file whose size is
// exactly the cap, and a loop that treated a true value as proof of lost data would
// have refused a complete file. The cost of not depending on it is one extra request
// in that case, which is cheaper than a wrong refusal.
//
// Every chunk is a separately signed request with its own nonce and timestamp, so the
// loop needs no protocol change and gains no replay weakness.
func fetchWholeFile(client *Client, options Options, write func([]byte) error) (int64, error) {
	offset := options.Offset
	remaining := options.Length
	var total int64

	for {
		requested := int64(chunkBytes)
		if remaining > 0 && remaining < requested {
			requested = remaining
		}

		chunkOptions := options
		chunkOptions.Offset = offset
		chunkOptions.Length = requested

		envelope, err := client.Send(chunkOptions)
		if err != nil {
			return total, err
		}
		if !envelope.Succeeded() {
			return total, fmt.Errorf("%s: %s", envelope.Code.Name(), envelope.Message)
		}

		var chunk readChunk
		if err := json.Unmarshal(envelope.Data, &chunk); err != nil {
			return total, fmt.Errorf("decode read result: %w", err)
		}

		if chunk.Size > 0 {
			if err := write(chunk.Content); err != nil {
				return total, err
			}
			total += chunk.Size
			offset += chunk.Size
			if remaining > 0 {
				remaining -= chunk.Size
			}
		}

		// A zero-size chunk ends the loop. An empty file stops on the first response
		// because `truncated` is false, not because of this check; this check stops a
		// response that claims more remains but delivered nothing, which would
		// otherwise spin forever. It is checked before the budget so a spent budget
		// cannot turn a contradictory response into another request.
		if chunk.Size == 0 || !chunk.Truncated {
			return total, nil
		}
		if options.Length > 0 && remaining == 0 {
			return total, nil
		}
	}
}

// destination is where a result is written. It exists so the three operations share
// one writer and one failure rule: a destination that exists always holds a complete
// result.
type destination struct {
	// writer receives the payload.
	writer io.Writer
	// file is the temporary file when the destination is a local path, and nil when
	// the destination is stdout.
	file *os.File
	// temporary is the temporary file's path, removed on failure.
	temporary string
	// final is the destination path, renamed into place on success.
	final string
}

// openDestination prepares the output for one invocation.
//
// A local path is written through a temporary file in the same directory and renamed
// into place only after every byte has been written. The same directory is required
// because a rename across filesystems is a copy, and a copy is not atomic. The
// consequence is the property the caller relies on: a destination file that exists is
// a complete file, never a half-written one.
//
// An existing destination is refused unless Force is set. A read tool that silently
// replaced a local file would destroy work the caller never asked it to touch.
func openDestination(options Options, stdout io.Writer) (*destination, error) {
	if options.Output == "" || options.Output == stdoutDestination {
		return &destination{writer: stdout}, nil
	}

	final := options.Output
	if !options.Force {
		if _, err := os.Lstat(final); err == nil {
			return nil, fmt.Errorf("%w: %s already exists; pass --force to replace it", ErrUsage, final)
		} else if !errors.Is(err, os.ErrNotExist) {
			return nil, fmt.Errorf("inspect %s: %w", final, err)
		}
	}

	directory := filepath.Dir(final)
	temporary, err := os.CreateTemp(directory, "."+filepath.Base(final)+".part-*")
	if err != nil {
		return nil, fmt.Errorf("create a temporary file in %s: %w", directory, err)
	}
	return &destination{writer: temporary, file: temporary, temporary: temporary.Name(), final: final}, nil
}

// commit finishes the write.
//
// A stdout destination has nothing to finish. A file destination is flushed, closed
// and renamed over the final path, so the rename is the moment the result becomes
// visible and it happens only after the content is complete.
func (d *destination) commit() error {
	if d.file == nil {
		return nil
	}
	if err := d.file.Sync(); err != nil {
		d.abort()
		return fmt.Errorf("flush %s: %w", d.temporary, err)
	}
	if err := d.file.Close(); err != nil {
		d.abort()
		return fmt.Errorf("close %s: %w", d.temporary, err)
	}
	d.file = nil
	if err := os.Rename(d.temporary, d.final); err != nil {
		d.abort()
		return fmt.Errorf("move %s into place: %w", d.temporary, err)
	}
	d.temporary = ""
	return nil
}

// abort removes the temporary file and leaves the destination untouched.
//
// It is safe to call after commit, because commit clears the temporary path. A
// failure path that ran twice must not delete a file it already renamed.
func (d *destination) abort() {
	if d.file != nil {
		_ = d.file.Close()
		d.file = nil
	}
	if d.temporary != "" {
		if err := os.Remove(d.temporary); err != nil && !errors.Is(err, os.ErrNotExist) {
			fmt.Fprintf(os.Stderr, "connector-server cli: could not remove %s: %v\n", d.temporary, err)
		}
		d.temporary = ""
	}
}

// writeToDestination performs the whole invocation against the chosen destination.
//
// `file.read` is the only operation that loops, because it is the only one whose
// payload is bounded by a cap. `file.list` and `file.stat` answer in one response, so
// they are sent once. `-o` still applies to them, because the flag means "where the
// result goes" and a caller should not have to remember which operation accepts it.
//
// The first request is issued here rather than by the caller, so a whole-file read
// does not fetch its first chunk twice.
func writeToDestination(client *Client, options Options, stdout, stderr io.Writer) error {
	target, err := openDestination(options, stdout)
	if err != nil {
		return err
	}

	if options.Operation == protocol.OperationFileRead {
		total, err := fetchWholeFile(client, options, func(content []byte) error {
			_, writeErr := target.writer.Write(content)
			return writeErr
		})
		if err != nil {
			target.abort()
			return err
		}
		if err := target.commit(); err != nil {
			return err
		}
		if options.Output != "" && options.Output != stdoutDestination {
			fmt.Fprintf(stderr, "connector-server cli: wrote %d bytes to %s\n", total, options.Output)
		}
		return nil
	}

	envelope, err := client.Send(options)
	if err != nil {
		target.abort()
		return err
	}
	if !envelope.Succeeded() {
		target.abort()
		return fmt.Errorf("%s: %s", envelope.Code.Name(), envelope.Message)
	}
	if err := writeResult(target.writer, stderr, options.Operation, envelope, false); err != nil {
		target.abort()
		return err
	}
	return target.commit()
}
