package server

import (
	"bytes"
	"net/http/httptest"
	"testing"
)

func TestDecodeJSONRejectsTrailingAndUnknownData(t *testing.T) {
	for _, body := range []string{`{"known":1}{"extra":2}`, `{"unknown":1}`} {
		r := httptest.NewRequest("POST", "/", bytes.NewBufferString(body))
		w := httptest.NewRecorder()
		var target struct {
			Known int `json:"known"`
		}
		if err := decodeJSON(w, r, &target, 1024); err == nil {
			t.Fatalf("accepted malformed body %s", body)
		}
	}
}
func TestParseIntAndQueryOptionsBoundaries(t *testing.T) {
	if parseInt("bad", 7) != 7 || parseInt("-1", 7) != 7 || parseInt("3", 7) != 3 {
		t.Fatal("parseInt boundaries failed")
	}
	r := httptest.NewRequest("GET", "/?offset=2&limit=5&sort_key=update_at_ms&order_by=desc", nil)
	o := queryOptions(r)
	if o.Offset != 2 || o.Limit != 5 || o.SortKey != "update_at_ms" || o.OrderBy != "desc" {
		t.Fatalf("options=%+v", o)
	}
}
