package node

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// dialTimeout bounds the connection attempt.
//
// A dial that hangs is a Node that appears to be starting and is not. The timeout is
// short because a Server that cannot accept a connection in this window is a Server
// the operator needs to hear about now, not after a long wait.
const dialTimeout = 15 * time.Second

// handshakeTimeout bounds the hello exchange on the Node side.
//
// It matches the Server's bound, so a Node and a Server that disagree about how long
// a handshake may take do not both wait for the other.
const handshakeTimeout = 10 * time.Second

// reconnectDelay is how long the Node waits before dialing again.
//
// The delay exists so a Server that is down does not turn into a tight loop of
// connection attempts. It is a fixed delay rather than a backoff because a Node is a
// long-lived process that must reconnect promptly once the Server returns, and a
// backoff that has grown to minutes would leave it idle long after the Server is
// healthy.
const reconnectDelay = 5 * time.Second

// ErrHandshakeRefused reports that the Server refused the hello.
var ErrHandshakeRefused = errors.New("the server refused the handshake")

// Dialer connects a Node to a Server and keeps the channel open.
//
// It owns the connection lifecycle and nothing about permissions. Every request that
// arrives is handed to the session, which hands it to the dispatcher, which consults
// the Node's authority. The dialer never decides whether an operation is allowed,
// because that decision belongs to the authority and nowhere else.
type Dialer struct {
	config          Config
	holder          *IdentityHolder
	identityPath    string
	credentialsPath string
	dispatcher      *Dispatcher
	logger          *slog.Logger

	// identityChanged records that the watcher adopted a new node id during the last
	// poll. It is written and read only by the watcher goroutine, so it needs no
	// synchronisation; the value it describes is published through the holder.
	identityChanged bool

	// identityChanges carries one signal per adopted identity change. It is created
	// by Run and is nil for a dialer that is never run, which is what a test that
	// drives a single connection wants: a nil channel never delivers, so no identity
	// change can drop the connection under test.
	identityChanges <-chan struct{}

	// identityChangeRequests is the sending end of the same channel, published so a
	// console can ask for a channel drop after it replaces the node id in memory. It
	// is guarded by identityChangeMutex because Run publishes it from the goroutine
	// that starts the dialer while the console reads it from the goroutine that reads
	// commands, and an unsynchronised write there is a data race the race detector
	// reports.
	//
	// It is nil until Run starts, and a nil value makes RequestIdentityChange a no-op:
	// a dialer that is not running has no channel to drop.
	identityChangeRequests chan<- struct{}
	identityChangeMutex    sync.Mutex
}

// NewDialer builds a dialer serving one fixed identity.
//
// A nil logger falls back to the default logger. A nil dispatcher is not substituted,
// because a dialer that cannot dispatch would accept requests and then have no
// answer, and the only safe invented answer is a refusal that the caller cannot
// distinguish from a policy decision.
//
// The identity is wrapped in a holder that nothing replaces, so this constructor
// describes a Node whose identifier cannot change while it runs. The process uses
// NewDialerWithHolder instead, because a Node that can be regenerated must adopt the
// new identifier rather than keep serving the old one.
func NewDialer(config Config, nodeID string, credentials *security.CredentialSet, dispatcher *Dispatcher, logger *slog.Logger) (*Dialer, error) {
	return NewDialerWithHolder(config, NewIdentityHolder(nodeID, credentials), dispatcher, logger)
}

// NewDialerWithHolder builds a dialer that serves whatever identity the holder
// currently carries.
//
// The holder is shared with the dispatcher, so the identifier the dialer announces in
// `hello` and the identifier the dispatcher compares a request against are the same
// value. Two separate holders would let a regeneration be adopted by one and not the
// other, which would leave the Node announcing one identity and checking another.
//
// The two file paths are where the watcher looks for a regenerated identifier and a
// changed credential set. An empty path disables watching that file, which is what a
// test that drives the dialer directly wants.
func NewDialerWithHolder(config Config, holder *IdentityHolder, dispatcher *Dispatcher, logger *slog.Logger) (*Dialer, error) {
	if dispatcher == nil {
		return nil, fmt.Errorf("dispatcher is nil")
	}
	if holder == nil {
		return nil, fmt.Errorf("identity holder is nil")
	}
	if err := security.ValidateNodeID(holder.NodeID()); err != nil {
		return nil, fmt.Errorf("node identity is unusable: %w", err)
	}
	if logger == nil {
		logger = slog.Default()
	}
	// An empty config directory means the caller has no file to watch. IdentityPath("")
	// would return the relative name "identity", which would make the watcher poll
	// whatever directory the process happens to run from, so the paths are left empty
	// instead.
	identityPath := ""
	credentialsPath := ""
	if config.ConfigDir != "" {
		identityPath = IdentityPath(config.ConfigDir)
		credentialsPath = CredentialsPath(config.ConfigDir)
	}
	return &Dialer{
		config:          config,
		holder:          holder,
		identityPath:    identityPath,
		credentialsPath: credentialsPath,
		dispatcher:      dispatcher,
		logger:          logger,
	}, nil
}

// Run connects and serves until the context is cancelled.
//
// A dropped connection is retried rather than treated as fatal, because a Node is a
// long-lived process on a personal computer: a laptop that sleeps, a network that
// changes and a Server that restarts are ordinary events, and a Node that exited on
// the first one would need a supervisor to do what this loop does.
//
// The context is the only way out. A cancellation during a dial, during the handshake
// or during a session all return promptly, so a shutdown does not wait for a
// reconnect delay to expire.
func (d *Dialer) Run(ctx context.Context) error {
	// The watcher is started here rather than in the constructor, because a dialer
	// that is built and never run must not leave a goroutine polling a file. It stops
	// with the context, so a shutdown leaves nothing behind.
	changes := make(chan struct{}, 1)
	go d.watchIdentity(ctx, changes)

	// The sending end is published so a console can ask for a channel drop after it
	// replaces the node id in memory. A stateless Node has no identity file, so the
	// watcher has nothing to poll and this is the only way a regenerated address can
	// reach the dialer.
	d.identityChangeMutex.Lock()
	d.identityChangeRequests = changes
	d.identityChangeMutex.Unlock()
	defer func() {
		d.identityChangeMutex.Lock()
		d.identityChangeRequests = nil
		d.identityChangeMutex.Unlock()
	}()
	// The channel is stored on the dialer so connectOnce keeps its single argument. A
	// test that drives one connection directly leaves the field nil, and a nil channel
	// blocks forever, which is the behaviour such a test wants: no identity change can
	// arrive because no watcher is running.
	d.identityChanges = changes

	for {
		if err := ctx.Err(); err != nil {
			return nil
		}

		// A change that arrived while no channel was live must not drop the channel
		// that is about to be established with the new identity: the reconnect below
		// already dials with the identifier the watcher adopted.
		discardPendingIdentityChange(changes)

		err := d.connectOnce(ctx)
		if err != nil && !errors.Is(err, context.Canceled) && !errors.Is(err, context.DeadlineExceeded) {
			d.logger.Warn("channel ended", "error", err, "retry_in", reconnectDelay)
		}

		select {
		case <-ctx.Done():
			return nil
		case <-time.After(reconnectDelay):
		}
	}
}

// RequestIdentityChange asks the dialer to drop the live channel.
//
// It exists for the console. A file-backed Node learns about a regenerated address from
// the watcher, which polls the identity file; a stateless Node has no file, so the
// console is the only thing that can tell the dialer its identity changed. Without this
// the Node would keep a channel authenticated under an address it no longer serves.
//
// The request is a no-op when the dialer is not running, because a dialer that is not
// running has no channel to drop. It never blocks: the channel is buffered and a pending
// signal is drained before the next dial, so a request that arrives while the Node is
// disconnected does not drop the channel that is about to be established with the new
// identity.
func (d *Dialer) RequestIdentityChange() {
	d.identityChangeMutex.Lock()
	requests := d.identityChangeRequests
	d.identityChangeMutex.Unlock()

	if requests == nil {
		return
	}
	select {
	case requests <- struct{}{}:
	default:
	}
}

// connectOnce dials, performs the handshake and serves one connection.
//
// The handshake is a fixed exchange: the Node sends hello, the Server answers with
// hello_confirm or an error frame. A refusal is returned as ErrHandshakeRefused rather
// than retried immediately, because a wrong tunnel token does not become right by
// trying again, and a tight retry loop against a refusing Server is a denial of
// service the Node inflicts on itself.
func (d *Dialer) connectOnce(ctx context.Context) error {
	conn, err := d.dial(ctx)
	if err != nil {
		return err
	}
	defer func() {
		if err := conn.Close(); err != nil {
			d.logger.Debug("closing the channel reported an error", "error", err)
		}
	}()

	// A cancellation cannot interrupt a blocked websocket read, so the connection is
	// closed when the context ends. Without this the session would observe the
	// cancellation only after the next frame arrived, and a Node with an idle channel
	// would ignore a shutdown indefinitely.
	stopWatcher := context.AfterFunc(ctx, func() {
		if err := conn.Close(); err != nil {
			d.logger.Debug("closing the channel during shutdown reported an error", "error", err)
		}
	})
	defer stopWatcher()

	// A regenerated identifier drops this channel, because the channel was
	// authenticated with a name that no longer exists. The connection is closed rather
	// than the session being told to stop, because a blocked read only ends when the
	// socket does.
	changeCtx, stopChangeWatcher := identityChangeContext(ctx, d.identityChanges)
	defer stopChangeWatcher()

	// The identifier is captured before the handshake so the log names the identity
	// this channel was authenticated with. Reading the holder inside the callback would
	// report the newly adopted value instead, which is the one the channel does not
	// have.
	authenticatedID := d.holder.NodeID()
	stopIdentityWatcher := context.AfterFunc(changeCtx, func() {
		// changeCtx is derived from ctx, so it is cancelled both when the identity
		// signal fires and when the session context ends. Only the first is an identity
		// change; a shutdown must not be reported as one, because an operator reading
		// the log would look for a regeneration that never happened.
		//
		// The shutdown branch closes nothing, because the watcher registered on ctx
		// above already closes the connection when the context ends. Closing it here as
		// well would be a second close of the same socket.
		if ctx.Err() != nil {
			return
		}
		d.logger.Info("identity changed; closing the channel authenticated with the retired node id",
			"node_id", authenticatedID,
		)
		if err := conn.Close(); err != nil {
			d.logger.Debug("closing the channel after an identity change reported an error", "error", err)
		}
	})
	defer stopIdentityWatcher()

	transport, err := d.handshake(conn)
	if err != nil {
		return err
	}

	d.logger.Info("channel established", "node_id", authenticatedID, "server", d.config.ServerURL)

	frames, err := NewSocketFrameConn(conn)
	if err != nil {
		return err
	}

	session := NewSession(d.dispatcher, frames, d.logger).WithTransport(transport)
	err = session.Serve(ctx)
	if ctx.Err() != nil {
		// The read failed because this side closed the connection to honour the
		// cancellation, so the error describes the shutdown rather than a fault.
		return nil
	}
	if changeCtx.Err() != nil {
		// The read failed because the identity changed and this side closed the
		// channel. The reconnect dials with the identifier the watcher adopted, so this
		// is a normal transition rather than a fault worth warning about.
		return nil
	}
	return err
}

// dial opens the websocket connection.
//
// The dial is bounded by a timeout derived from the context, so a cancellation during
// the dial returns immediately instead of waiting for the dial timeout.
func (d *Dialer) dial(ctx context.Context) (*websocket.Conn, error) {
	dialCtx, cancel := context.WithTimeout(ctx, dialTimeout)
	defer cancel()

	dialer := websocket.Dialer{
		HandshakeTimeout: dialTimeout,
		// The proxy is taken from the environment, because a Node behind a corporate
		// proxy has no other way to reach the Server and the operator has already
		// expressed the proxy in the environment they use for everything else.
		Proxy: http.ProxyFromEnvironment,
	}

	conn, response, err := dialer.DialContext(dialCtx, d.config.ServerURL, nil)
	if err != nil {
		if response != nil {
			return nil, fmt.Errorf("dial %s: %w (status %s)", d.config.ServerURL, err, response.Status)
		}
		return nil, fmt.Errorf("dial %s: %w", d.config.ServerURL, err)
	}
	return conn, nil
}

// handshake sends hello and waits for the confirmation, and returns the content
// transport the Server selected.
//
// The tunnel token is written into the hello frame and released with it. It is never
// copied into a field of the dialer, so a reconnect re-reads it from the configuration
// instead of replaying a stored copy.
//
// The returned transport is the Server's answer, not the Node's preference. A Server
// that answers with no transport leaves the Node on the original JSON transport, so an
// older Server keeps working without a protocol change.
func (d *Dialer) handshake(conn *websocket.Conn) (protocol.FileTransportVersion, error) {
	hello := protocol.Hello{
		Version:        protocol.Version,
		NodeID:         d.holder.NodeID(),
		TunnelToken:    []byte(d.config.TunnelToken),
		Operations:     d.advertisedOperations(),
		Scopes:         d.advertisedScopes(),
		FileTransports: []protocol.FileTransportVersion{protocol.FileTransportBinaryV1},
	}

	payload, err := json.Marshal(hello)
	if err != nil {
		return "", fmt.Errorf("encode hello: %w", err)
	}
	frame := protocol.Frame{Type: protocol.FrameHello, Payload: payload}
	encoded, err := json.Marshal(frame)
	if err != nil {
		return "", fmt.Errorf("encode hello frame: %w", err)
	}

	if err := conn.SetWriteDeadline(time.Now().Add(handshakeTimeout)); err != nil {
		return "", fmt.Errorf("set the handshake write deadline: %w", err)
	}
	if err := conn.WriteMessage(websocket.TextMessage, encoded); err != nil {
		return "", fmt.Errorf("write hello: %w", err)
	}

	if err := conn.SetReadDeadline(time.Now().Add(handshakeTimeout)); err != nil {
		return "", fmt.Errorf("set the handshake read deadline: %w", err)
	}
	_, data, err := conn.ReadMessage()
	if err != nil {
		return "", fmt.Errorf("read hello_confirm: %w", err)
	}

	var answer protocol.Frame
	if err := json.Unmarshal(data, &answer); err != nil {
		return "", fmt.Errorf("decode hello_confirm frame: %w", err)
	}

	var selected protocol.FileTransportVersion
	switch answer.Type {
	case protocol.FrameHelloConfirm:
		var confirm protocol.HelloConfirm
		if err := json.Unmarshal(answer.Payload, &confirm); err != nil {
			return "", fmt.Errorf("decode hello_confirm payload: %w", err)
		}
		if confirm.Version != protocol.Version {
			return "", fmt.Errorf("server speaks protocol %q, this node speaks %q", confirm.Version, protocol.Version)
		}
		if err := validateSelectedTransport(confirm.FileTransport); err != nil {
			return "", err
		}
		selected = confirm.FileTransport
		d.logger.Info("handshake accepted",
			"node_id", d.holder.NodeID(),
			"generation", confirm.Generation,
			"file_transport", transportName(selected),
		)
	case protocol.FrameError:
		var refusal protocol.Response
		if err := json.Unmarshal(answer.Payload, &refusal); err != nil {
			return "", fmt.Errorf("%w: unreadable refusal", ErrHandshakeRefused)
		}
		return "", fmt.Errorf("%w: %s", ErrHandshakeRefused, refusal.Code.Name())
	default:
		return "", fmt.Errorf("server answered the handshake with %q", string(answer.Type))
	}

	// The handshake deadlines are cleared so a long-lived channel is not closed by a
	// deadline set for the exchange that has already finished.
	if err := conn.SetReadDeadline(time.Time{}); err != nil {
		return "", fmt.Errorf("clear the handshake read deadline: %w", err)
	}
	if err := conn.SetWriteDeadline(time.Time{}); err != nil {
		return "", fmt.Errorf("clear the handshake write deadline: %w", err)
	}
	return selected, nil
}

// validateSelectedTransport refuses a transport this Node did not offer.
//
// The Server selects from the list the Node sent, so a value outside that list is a
// Server that answered a different question. Accepting it would mean encoding content
// in a representation this Node never claimed to support, and the failure would appear
// as unreadable bytes rather than as a refused handshake.
func validateSelectedTransport(selected protocol.FileTransportVersion) error {
	switch selected {
	case "":
		// No transport selected: the original JSON transport, which every version
		// supports.
		return nil
	case protocol.FileTransportBinaryV1:
		return nil
	default:
		return fmt.Errorf("server selected file transport %q, which this node did not offer", string(selected))
	}
}

// transportName renders a transport for a log line, naming the JSON fallback rather
// than printing an empty value a reader would have to interpret.
func transportName(transport protocol.FileTransportVersion) string {
	if transport == "" {
		return "json"
	}
	return string(transport)
}

// advertisedOperations returns the operations this Node can serve.
//
// The list is derived from the protocol rather than from the policy, because it
// describes what the binary implements. What a caller may actually do is decided per
// request by the authority, so advertising an operation here grants nothing.
func (d *Dialer) advertisedOperations() []string {
	candidates := []protocol.Operation{
		protocol.OperationFileRead,
		protocol.OperationFileList,
		protocol.OperationFileStat,
	}
	operations := make([]string, 0, len(candidates))
	for _, operation := range candidates {
		if operation.Enabled() {
			operations = append(operations, string(operation))
		}
	}
	return operations
}

// advertisedScopes returns the scope names the policy defines.
//
// The names are informational: the Server does not use them to decide anything,
// because the Node is the only authority for permissions. They exist so an operator
// reading a log can see what a Node offers without asking it.
//
// A dispatcher with no authority advertises nothing rather than panicking. A nil
// authority is a legal dispatcher, because the only safe invented answer is a refusal
// and a nil authority already produces one; a crash during the handshake would instead
// turn a wiring mistake into a Node that cannot connect at all.
func (d *Dialer) advertisedScopes() []string {
	if d.dispatcher == nil || d.dispatcher.authority == nil {
		return nil
	}

	names := d.dispatcher.authority.ScopeNames()
	scopes := make([]string, 0, len(names))
	for _, name := range names {
		scopes = append(scopes, string(name))
	}
	return scopes
}
