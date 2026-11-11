// Command messages-bound-gencerts mints the TLS material for the messages
// display-bound manual check.
//
// It exists because the harness certificates are valid for one hour, so a
// certificate directory reused from an earlier run is expired and the Endpoint
// fails the mTLS handshake. That failure is reported as "certificate has expired
// or is not yet valid", which looks like a transport fault rather than a stale
// artifact, so the material must be minted per run instead of reused.
//
// The generator reuses the harness implementation so the certificate identities
// match what the Server and Endpoint expect: the client certificate carries the
// DNS SAN endpoint-1, which is the Endpoint identity the Server verifies.
package main

import (
	"fmt"
	"os"

	"topsailai_agent_cluster/tests/harness"
)

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: messages-bound-gencerts <directory>")
		os.Exit(2)
	}
	files, err := harness.CertificatesE(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, "cert:", err)
		os.Exit(1)
	}
	fmt.Println(files.CA)
	fmt.Println(files.ServerCert)
	fmt.Println(files.ServerKey)
	fmt.Println(files.ClientCert)
	fmt.Println(files.ClientKey)
}
