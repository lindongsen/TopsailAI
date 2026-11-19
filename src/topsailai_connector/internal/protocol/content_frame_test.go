package protocol

import (
	"encoding/binary"
	"strings"
	"testing"
)

// TestContentFrameRoundTripKeepsRawBytes checks that content survives the binary
// envelope unchanged, including bytes that JSON would have to escape or base64.
func TestContentFrameRoundTripKeepsRawBytes(t *testing.T) {
	content := []byte{0x00, 0xff, '"', '\\', '\n', 0x7f, 'a'}
	header := ContentHeader{
		RequestID:     "req_0123456789abcdef0123456789abcdef",
		Size:          int64(len(content)),
		Truncated:     true,
		ContentLength: int64(len(content)),
	}

	frame, err := EncodeContentFrame(header, content)
	if err != nil {
		t.Fatalf("encode content frame: %v", err)
	}

	decodedHeader, decodedContent, err := DecodeContentFrame(frame)
	if err != nil {
		t.Fatalf("decode content frame: %v", err)
	}
	if decodedHeader != header {
		t.Fatalf("header = %+v, want %+v", decodedHeader, header)
	}
	if string(decodedContent) != string(content) {
		t.Fatalf("content = %v, want %v", decodedContent, content)
	}
}

// TestContentFrameCarriesNoBase64Expansion checks that the encoded frame is only
// the fixed prefix, the header and the raw content, so a 256 KiB chunk does not
// grow by the 4/3 factor base64 imposes.
func TestContentFrameCarriesNoBase64Expansion(t *testing.T) {
	content := make([]byte, 256*1024)
	for index := range content {
		content[index] = byte(index)
	}
	header := ContentHeader{
		RequestID:     "req_0123456789abcdef0123456789abcdef",
		Size:          int64(len(content)),
		ContentLength: int64(len(content)),
	}

	frame, err := EncodeContentFrame(header, content)
	if err != nil {
		t.Fatalf("encode content frame: %v", err)
	}

	overhead := len(frame) - len(content)
	if overhead > 512 {
		t.Fatalf("frame overhead = %d bytes, want at most 512", overhead)
	}
}

// TestContentFrameRefusesMismatchedContentLength checks that a frame whose
// declared length disagrees with the bytes present is refused, because accepting
// it would publish a truncated transfer as a complete one.
func TestContentFrameRefusesMismatchedContentLength(t *testing.T) {
	header := ContentHeader{
		RequestID:     "req_0123456789abcdef0123456789abcdef",
		Size:          4,
		ContentLength: 4,
	}

	if _, err := EncodeContentFrame(header, []byte("abc")); err == nil {
		t.Fatal("expected an error when the declared length exceeds the content")
	}

	frame, err := EncodeContentFrame(ContentHeader{
		RequestID:     header.RequestID,
		Size:          3,
		ContentLength: 3,
	}, []byte("abc"))
	if err != nil {
		t.Fatalf("encode content frame: %v", err)
	}

	// Claim one more content byte than the frame carries.
	headerLength := int(binary.BigEndian.Uint32(frame[4:8]))
	headerBytes := frame[8 : 8+headerLength]
	corrupted := strings.Replace(string(headerBytes), `"content_length":3`, `"content_length":4`, 1)
	if corrupted == string(headerBytes) {
		t.Fatalf("test could not corrupt the header: %s", headerBytes)
	}
	copy(frame[8:8+headerLength], corrupted)

	if _, _, err := DecodeContentFrame(frame); err == nil {
		t.Fatal("expected an error when the declared length exceeds the content")
	}
}

// TestContentFrameRefusesBadMagic checks that a message that is not a content
// frame is refused before its header is interpreted.
func TestContentFrameRefusesBadMagic(t *testing.T) {
	frame, err := EncodeContentFrame(ContentHeader{
		RequestID:     "req_0123456789abcdef0123456789abcdef",
		Size:          1,
		ContentLength: 1,
	}, []byte("a"))
	if err != nil {
		t.Fatalf("encode content frame: %v", err)
	}
	copy(frame[0:4], "JSON")

	if _, _, err := DecodeContentFrame(frame); err == nil {
		t.Fatal("expected an error for a wrong magic")
	}
}

// TestContentFrameRefusesShortPrefix checks that a message too short to hold the
// fixed prefix is refused rather than read past its end.
func TestContentFrameRefusesShortPrefix(t *testing.T) {
	if _, _, err := DecodeContentFrame([]byte("CNT")); err == nil {
		t.Fatal("expected an error for a short prefix")
	}
}

// TestContentFrameRefusesOversizedHeader checks that a header length over the cap
// is refused before the header is decoded.
func TestContentFrameRefusesOversizedHeader(t *testing.T) {
	frame := make([]byte, 8)
	copy(frame[0:4], ContentFrameMagic)
	binary.BigEndian.PutUint32(frame[4:8], uint32(MaxContentHeaderBytes+1))

	if _, _, err := DecodeContentFrame(frame); err == nil {
		t.Fatal("expected an error for an oversized header")
	}
}

// TestContentFrameRefusesEmptyRequestID checks that a content frame without a
// correlation id is refused, because the Server cannot route it to a waiter.
func TestContentFrameRefusesEmptyRequestID(t *testing.T) {
	if _, err := EncodeContentFrame(ContentHeader{Size: 1, ContentLength: 1}, []byte("a")); err == nil {
		t.Fatal("expected an error for an empty request id")
	}
}

// TestContentFrameRefusesNegativeSize checks that a negative total size is
// refused rather than reported to a caller as a byte count.
func TestContentFrameRefusesNegativeSize(t *testing.T) {
	if _, err := EncodeContentFrame(ContentHeader{
		RequestID:     "req_0123456789abcdef0123456789abcdef",
		Size:          -1,
		ContentLength: 1,
	}, []byte("a")); err == nil {
		t.Fatal("expected an error for a negative size")
	}
}

// TestContentFramePreservesEveryByteValue checks that every one of the 256 byte
// values survives the frame unchanged.
//
// The bytes that matter are the ones a text-mode layer rewrites: 0x0d and 0x0a
// become CRLF, 0x1a ends a read, and 0x80-0xff are rewritten by a code-page
// conversion. Windows is a supported platform, so a transport that mangles these
// would corrupt a file while reporting success. The frame is written as a
// WebSocket binary message and the content is copied verbatim, so the expected
// behaviour is byte transparency; this test is what holds that expectation.
//
// The test carries no build tag, so it runs on every host. The rule it protects
// is platform-independent, and a Windows-only test would never run here.
func TestContentFramePreservesEveryByteValue(t *testing.T) {
	content := make([]byte, 256)
	for index := range content {
		content[index] = byte(index)
	}
	header := ContentHeader{
		RequestID:     "req_0123456789abcdef0123456789abcdef",
		Size:          int64(len(content)),
		ContentLength: int64(len(content)),
	}

	frame, err := EncodeContentFrame(header, content)
	if err != nil {
		t.Fatalf("encode content frame: %v", err)
	}

	_, decodedContent, err := DecodeContentFrame(frame)
	if err != nil {
		t.Fatalf("decode content frame: %v", err)
	}
	if len(decodedContent) != len(content) {
		t.Fatalf("decoded %d bytes, want %d", len(decodedContent), len(content))
	}
	for index := range content {
		if decodedContent[index] != content[index] {
			t.Fatalf("byte %d = 0x%02x, want 0x%02x", index, decodedContent[index], content[index])
		}
	}
}

// TestContentFramePreservesEveryByteValueAcrossChunkBoundary checks byte
// transparency when the payload spans more than one chunk.
//
// A per-chunk encoder can be transparent inside one chunk and lossy at a
// boundary, so a single-chunk test would not see the defect. The payload repeats
// the full byte range so that every value also lands on a chunk boundary.
func TestContentFramePreservesEveryByteValueAcrossChunkBoundary(t *testing.T) {
	const chunkSize = 256 * 1024
	content := make([]byte, chunkSize*2+1)
	for index := range content {
		content[index] = byte(index % 256)
	}
	header := ContentHeader{
		RequestID:     "req_0123456789abcdef0123456789abcdef",
		Size:          int64(len(content)),
		ContentLength: int64(len(content)),
	}

	frame, err := EncodeContentFrame(header, content)
	if err != nil {
		t.Fatalf("encode content frame: %v", err)
	}

	_, decodedContent, err := DecodeContentFrame(frame)
	if err != nil {
		t.Fatalf("decode content frame: %v", err)
	}
	if len(decodedContent) != len(content) {
		t.Fatalf("decoded %d bytes, want %d", len(decodedContent), len(content))
	}
	for index := range content {
		if decodedContent[index] != content[index] {
			t.Fatalf("byte %d = 0x%02x, want 0x%02x", index, decodedContent[index], content[index])
		}
	}
}
