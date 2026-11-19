package protocol

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
)

// ContentFrameMagic marks a binary content message. The four bytes let the
// receiver refuse a message that is not a content frame before it decodes a
// header, so a misrouted text frame cannot be read as content.
const ContentFrameMagic = "CNT1"

// MaxContentHeaderBytes bounds the JSON header of a content frame.
//
// The header carries identifiers and counters only, so a header larger than this
// is a peer spending the receiver's memory on metadata rather than on content.
const MaxContentHeaderBytes = 4096

// ContentHeader is the metadata that travels in front of the raw content bytes.
//
// The content itself is not a field here. It follows the header as raw bytes, so
// the receiver never base64-decodes or JSON-unescapes file content.
type ContentHeader struct {
	RequestID     string `json:"request_id"`
	Size          int64  `json:"size"`
	Truncated     bool   `json:"truncated"`
	ContentLength int64  `json:"content_length"`
}

// EncodeContentFrame builds one binary content message.
//
// The layout is fixed: magic, a big-endian header length, the JSON header, then
// the content bytes. A length prefix is used rather than a delimiter because file
// content may contain any byte, including the delimiter.
func EncodeContentFrame(header ContentHeader, content []byte) ([]byte, error) {
	if header.RequestID == "" {
		return nil, fmt.Errorf("content frame carries no request id")
	}
	if header.ContentLength != int64(len(content)) {
		return nil, fmt.Errorf("content length %d does not match %d content bytes", header.ContentLength, len(content))
	}
	if header.Size < 0 {
		return nil, fmt.Errorf("content size %d is negative", header.Size)
	}

	encodedHeader, err := json.Marshal(header)
	if err != nil {
		return nil, fmt.Errorf("encode content header: %w", err)
	}
	if len(encodedHeader) > MaxContentHeaderBytes {
		return nil, fmt.Errorf("content header is %d bytes, limit is %d", len(encodedHeader), MaxContentHeaderBytes)
	}

	frame := make([]byte, 8+len(encodedHeader)+len(content))
	copy(frame[0:4], ContentFrameMagic)
	binary.BigEndian.PutUint32(frame[4:8], uint32(len(encodedHeader)))
	copy(frame[8:8+len(encodedHeader)], encodedHeader)
	copy(frame[8+len(encodedHeader):], content)
	return frame, nil
}

// DecodeContentFrame splits one binary content message into its header and its
// content bytes.
//
// Every malformed shape is refused rather than repaired, and the declared content
// length must equal the bytes actually present. A frame that is short by one byte
// is a truncated transfer, and accepting it would publish a partial file as a
// complete one.
func DecodeContentFrame(frame []byte) (ContentHeader, []byte, error) {
	if len(frame) < 8 {
		return ContentHeader{}, nil, fmt.Errorf("content frame is %d bytes, shorter than its fixed prefix", len(frame))
	}
	if string(frame[0:4]) != ContentFrameMagic {
		return ContentHeader{}, nil, fmt.Errorf("content frame magic is %q, want %q", string(frame[0:4]), ContentFrameMagic)
	}

	headerLength := int(binary.BigEndian.Uint32(frame[4:8]))
	if headerLength == 0 {
		return ContentHeader{}, nil, fmt.Errorf("content frame carries an empty header")
	}
	if headerLength > MaxContentHeaderBytes {
		return ContentHeader{}, nil, fmt.Errorf("content header is %d bytes, limit is %d", headerLength, MaxContentHeaderBytes)
	}
	if 8+headerLength > len(frame) {
		return ContentHeader{}, nil, fmt.Errorf("content header claims %d bytes but only %d remain", headerLength, len(frame)-8)
	}

	var header ContentHeader
	if err := json.Unmarshal(frame[8:8+headerLength], &header); err != nil {
		return ContentHeader{}, nil, fmt.Errorf("decode content header: %w", err)
	}
	if header.RequestID == "" {
		return ContentHeader{}, nil, fmt.Errorf("content frame carries no request id")
	}
	if header.Size < 0 {
		return ContentHeader{}, nil, fmt.Errorf("content size %d is negative", header.Size)
	}

	content := frame[8+headerLength:]
	if header.ContentLength != int64(len(content)) {
		return ContentHeader{}, nil, fmt.Errorf("content length %d does not match %d content bytes", header.ContentLength, len(content))
	}
	return header, content, nil
}
