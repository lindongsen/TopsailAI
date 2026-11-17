package tui

import (
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// TestMessagesCellRendersTwoCounts pins the cell projection. The two counts are
// rendered as data1/data2 in one cell, and an unmeasured row renders a dash
// rather than "0/0", because zero is a measurement nobody made.
func TestMessagesCellRendersTwoCounts(t *testing.T) {
	for _, tc := range []struct {
		name string
		row  SessionRow
		want string
	}{
		{
			name: "unmeasured row is a dash",
			row:  SessionRow{},
			want: "-",
		},
		{
			name: "measured row renders inbound then outbound",
			row:  SessionRow{Messages: &protocol.MessageCounts{Inbound: 7, Outbound: 3}},
			want: "7/3",
		},
		{
			name: "zero counts are a real measurement",
			row:  SessionRow{Messages: &protocol.MessageCounts{Inbound: 0, Outbound: 0}},
			want: "0/0",
		},
		{
			name: "large counts are not abbreviated",
			row:  SessionRow{Messages: &protocol.MessageCounts{Inbound: 1234567, Outbound: 89}},
			want: "1234567/89",
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := messagesCell(tc.row); got != tc.want {
				t.Fatalf("messagesCell=%q want=%q", got, tc.want)
			}
		})
	}
}

// TestMessagesColumnFollowsDrive pins the column position. The counts sit
// directly after DRIVER so the runtime facts about one session are read
// together, and the header is the field name the human asked for.
func TestMessagesColumnFollowsDrive(t *testing.T) {
	index := -1
	for position, column := range allColumns {
		if column.key == columnMessages {
			index = position
		}
	}
	if index < 0 {
		t.Fatal("messages column is missing from allColumns")
	}
	if allColumns[index-1].key != columnDrive {
		t.Fatalf("messages column follows %q, want %q", allColumns[index-1].key, columnDrive)
	}
	if allColumns[index].header != "MESSAGES" {
		t.Fatalf("messages header=%q want=MESSAGES", allColumns[index].header)
	}
}

// TestMessagesColumnRendersInTable proves the column reaches the rendered table
// and that an unmeasured row renders a dash rather than an empty cell.
func TestMessagesColumnRendersInTable(t *testing.T) {
	var out, errors strings.Builder
	rows := []SessionRow{
		{EndpointID: "endpoint-1", EndpointLabel: "host-1", ClusterSessionID: "res_1", ProviderSessionID: "provider-session-1", State: "running", CollectionStatus: protocol.CollectionSucceeded},
		{EndpointID: "endpoint-1", EndpointLabel: "host-1", ClusterSessionID: "res_2", ProviderSessionID: "provider-session-2", State: "running", CollectionStatus: protocol.CollectionSucceeded, Messages: &protocol.MessageCounts{Inbound: 7, Outbound: 3}},
	}
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{Location: time.UTC}); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSuffix(out.String(), "\n"), "\n")
	headerCells := strings.Split(lines[1], " │ ")
	messagesIndex := -1
	for position, cell := range headerCells {
		if strings.TrimSpace(cell) == "MESSAGES" {
			messagesIndex = position
		}
	}
	if messagesIndex < 0 {
		t.Fatalf("rendered header has no MESSAGES column: %q", lines[1])
	}
	absent := strings.Split(lines[3], " │ ")
	if got := strings.TrimSpace(absent[messagesIndex]); got != "-" {
		t.Fatalf("unmeasured messages cell=%q want=-", got)
	}
	present := strings.Split(lines[4], " │ ")
	if got := strings.TrimSpace(present[messagesIndex]); got != "7/3" {
		t.Fatalf("measured messages cell=%q want=7/3", got)
	}
}

// TestMessagesCellRendersUnmeasuredAsDash proves an absent count renders as an
// unmeasured marker rather than a zero, because a session with no live process
// has no counts to report and "0/0" would claim it was measured.
func TestMessagesCellRendersUnmeasuredAsDash(t *testing.T) {
	row := SessionRow{}
	if got := messagesCell(row); got != "-" {
		t.Fatalf("unmeasured messages cell=%q want=-", got)
	}
}
