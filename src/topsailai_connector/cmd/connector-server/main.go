// Command connector-server is the cloud-side entry point. It accepts Node
// connections and calls the operations a Node advertises.
//
// The skeleton only proves the package layout builds; the listener, the
// handshake and the operation dispatch are added by later logical units.
package main

import (
	"flag"
	"log"

	"topsailai_connector/internal/protocol"
)

func main() {
	listen := flag.String("listen", ":8443", "address the server listens on")
	flag.Parse()

	log.Printf("connector-server starting, protocol=%s listen=%s", protocol.Version, *listen)
}
