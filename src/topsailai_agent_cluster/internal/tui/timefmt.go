package tui

import "time"

// The CLI renders a time for a human, never as a raw epoch number. A number such
// as 1793885072943 is unreadable: an operator cannot tell whether it is today,
// last week or a different unit entirely, and comparing two of them by eye is
// hopeless.
//
// Three layouts exist because three surfaces have different constraints, and each
// one is justified rather than chosen for variety:
//
//   - layoutClock is a table cell. A cell has a width budget shared with the
//     columns that address a row, so it keeps the clock and drops the date. The
//     row's own stale marker carries the "this is not from now" signal, so the
//     date is not the only freshness evidence.
//   - layoutDateTime is a detail or standalone line. Such a line has no width
//     budget and can describe a value observed on an earlier day, so a bare clock
//     would make yesterday's observation look like today's.
//   - layoutDateTimeMillis is a conversation record. Two records can be written
//     inside the same second, so a coarser layout would make them look
//     simultaneous.
const (
	layoutClock          = "15:04:05"
	layoutDateTime       = "2006-01-02 15:04:05"
	layoutDateTimeMillis = "2006-01-02 15:04:05.000"
)

// unreportedTime is the single rendering of a time that was never reported. It is
// a dash rather than an empty cell or a zero, because a zero would read as a real
// instant and an empty cell would read as a formatting gap.
const unreportedTime = "-"

// formatClockTime renders one UTC epoch millisecond value as a clock time in the
// given location. It is the table-cell layout, so it is used only where a width
// budget forbids the date.
//
// A non-positive value means the time was never reported, which is not the same as
// an instant at the epoch, so it renders as unreportedTime instead of 00:00:00.
func formatClockTime(value int64, location *time.Location) string {
	if value <= 0 {
		return unreportedTime
	}
	return time.UnixMilli(value).In(resolveLocation(location)).Format(layoutClock)
}

// formatDateTime renders one UTC epoch millisecond value as a date and clock time
// in the given location. It is the detail-line layout, so it is used wherever the
// value can belong to an earlier day and the line has room for the date.
func formatDateTime(value int64, location *time.Location) string {
	if value <= 0 {
		return unreportedTime
	}
	return time.UnixMilli(value).In(resolveLocation(location)).Format(layoutDateTime)
}

// formatDateTimeMillis renders one UTC epoch millisecond value with its
// milliseconds, for a surface where two records can share a second.
func formatDateTimeMillis(value int64, location *time.Location) string {
	if value <= 0 {
		return unreportedTime
	}
	return time.UnixMilli(value).In(resolveLocation(location)).Format(layoutDateTimeMillis)
}

// optionalTimeValue unwraps an optional timestamp, reporting an absent value as
// zero so the shared formatters render it as unreported.
func optionalTimeValue(value *int64) int64 {
	if value == nil {
		return 0
	}
	return *value
}

// resolveLocation falls back to the local timezone, so a caller that has no
// explicit location still renders a time an operator can compare with their own
// clock.
func resolveLocation(location *time.Location) *time.Location {
	if location == nil {
		return time.Local
	}
	return location
}
