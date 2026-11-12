package genericcli

// callbackError distinguishes a consumer-requested stream stop from Provider
// protocol, transport and process failures.
type callbackError struct {
	cause error
}

func (e *callbackError) Error() string { return e.cause.Error() }

func (e *callbackError) Unwrap() error { return e.cause }
