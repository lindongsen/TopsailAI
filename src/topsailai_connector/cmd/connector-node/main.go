// Command connector-node is the personal-computer entry point. It dials the
// Server, keeps the link open and serves the operations its policy allows.
//
// The skeleton only proves the package layout builds; the dialer, the
// handshake and the operation handlers are added by later logical units.
package main

import (
	"flag"
	"log"

	"topsailai_connector/internal/protocol"
)

func main() {
	server := flag.String("server", "wss://127.0.0.1:8443/channel", "server channel address")
	flag.Parse()

	log.Printf("connector-node starting, protocol=%s server=%s", protocol.Version, *server)
}
