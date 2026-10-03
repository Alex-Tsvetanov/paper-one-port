// The cmux harness of hypotheses.md, Appendix B (CP8 of design/proposal.md): one listener split by
// cmux v0.1.5 with the matchers HTTP2(), HTTP1Fast(), TLS(), PrefixMatcher("SSH-") and, in the kinds
// with a fallback, Any() last; Go's net/http serves HTTP/1.1, h2c (prior knowledge, Server.Protocols'
// UnencryptedHTTP2, go1.24 and later) and TLS (crypto/tls, then HTTP/1.1 or h2 by ALPN); a minimal
// SSH handler and the SMTP fallback are the server's (hypotheses.md, section 2.1; bench/server/apps.hpp).
// design/competitor-survey.md, 2.10 and 2.11.
//
// Arguments (bench/competitors/cmux/cases.args and b3.args, rendered by competitors.py):
//
//	-port N       the listener (net.Listen: the backlog is net.core.somaxconn, net/sock_linux.go)
//	-timer-s N    cmux's SetReadTimeout in seconds (0: not set, cmux's default, no timeout)
//	-fallback     Any() last, to the SMTP handler
//	-cert F -key F  the test certificate and key (tests/fixtures/tls)
//
// GOMAXPROCS comes from the CPU affinity mask and the collector keeps Go's defaults (GOGC 100, no
// memory limit; runtime/debug docs). On SIGUSR1 the harness calls debug.FreeOSMemory and prints one
// JSON line with HeapInuse (WL7's collector step for the cmux harness; b3.py sends the signal, so no
// connection is opened for it). Prints "cmux: listening <port>".
//
// SIGTERM, which every runner sends to stop a system (bench/competitors/competitors.py, stop), ends
// the harness by a normal exit (M7): it closes the listener and the HTTP server, prints "cmux:
// stopped by SIGTERM" and returns from main, so the sanitizers' exit checks run (go build -asan's
// leak check at exit, the race detector's exit status). Go's default action for SIGTERM ended the
// process before them. Connections still being matched are not waited for: cmux's Serve waits for
// them, and a silent connection may wait for its read timeout; the exit closes them.
package main

import (
	"bufio"
	"crypto/tls"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"runtime"
	"runtime/debug"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/soheilhy/cmux"
)

var body = []byte("Hello, World!")

// stopping is set when SIGTERM starts the harness's end, so the listeners closing then are not errors.
var stopping atomic.Bool

func main() {
	port := flag.Int("port", 0, "the listener's port")
	timerS := flag.Int("timer-s", 0, "SetReadTimeout in seconds (0: not set)")
	fallback := flag.Bool("fallback", false, "Any() last, to the SMTP handler")
	certFile := flag.String("cert", "", "the test certificate")
	keyFile := flag.String("key", "", "the test key")
	flag.Parse()
	if *port <= 0 || *certFile == "" || *keyFile == "" {
		fmt.Fprintln(os.Stderr, "usage: -port N [-timer-s N] [-fallback] -cert F -key F")
		os.Exit(2)
	}
	// The test certificate; TLS 1.3 only and X25519 only, as the server's (section 2.1); no session
	// tickets. crypto/tls does not let a program choose TLS 1.3 cipher suites (crypto/tls docs,
	// Config.CipherSuites), so that one setting stays Go's. ALPN offers h2 and http/1.1.
	cert, err := tls.LoadX509KeyPair(*certFile, *keyFile)
	if err != nil {
		log.Fatalf("cmux: the test certificate: %v", err)
	}
	tlsConfig := &tls.Config{
		Certificates:           []tls.Certificate{cert},
		MinVersion:             tls.VersionTLS13,
		MaxVersion:             tls.VersionTLS13,
		CurvePreferences:       []tls.CurveID{tls.X25519},
		SessionTicketsDisabled: true,
		NextProtos:             []string{"h2", "http/1.1"},
	}

	l, err := net.Listen("tcp", "127.0.0.1:"+strconv.Itoa(*port))
	if err != nil {
		log.Fatalf("cmux: listen: %v", err)
	}
	m := cmux.New(l)
	if *timerS > 0 {
		m.SetReadTimeout(time.Duration(*timerS) * time.Second)
	}
	h2cL := m.Match(cmux.HTTP2())
	h1L := m.Match(cmux.HTTP1Fast())
	tlsL := m.Match(cmux.TLS())
	sshL := m.Match(cmux.PrefixMatcher("SSH-"))
	var anyL net.Listener
	if *fallback {
		anyL = m.Match(cmux.Any())
	}

	protocols := new(http.Protocols)
	protocols.SetHTTP1(true)
	protocols.SetHTTP2(true)
	protocols.SetUnencryptedHTTP2(true)
	srv := &http.Server{
		Handler:   http.HandlerFunc(hello),
		Protocols: protocols,
		// No per-connection logging (Appendix B: connection logging off in every system): net/http
		// otherwise logs each failed TLS handshake to the standard logger (http.Server.ErrorLog docs).
		ErrorLog: log.New(io.Discard, "", 0),
	}
	go serve(srv.Serve, h2cL)
	go serve(srv.Serve, h1L)
	go serve(srv.Serve, tls.NewListener(tlsL, tlsConfig))
	go acceptLoop(sshL, ssh)
	if anyL != nil {
		go acceptLoop(anyL, smtp)
	}

	usr1 := make(chan os.Signal, 1)
	signal.Notify(usr1, syscall.SIGUSR1)
	go collector(usr1)
	term := make(chan os.Signal, 1)
	signal.Notify(term, syscall.SIGTERM)

	served := make(chan error, 1)
	go func() { served <- m.Serve() }()
	fmt.Printf("cmux: listening %d (GOMAXPROCS %d, timer %d s, fallback %v)\n", *port, runtime.GOMAXPROCS(0), *timerS, *fallback)
	select {
	case <-term:
		stopping.Store(true)
		_ = l.Close()
		_ = srv.Close()
		fmt.Println("cmux: stopped by SIGTERM")
	case err := <-served:
		if err != nil && !strings.Contains(err.Error(), "use of closed network connection") {
			log.Fatalf("cmux: serve: %v", err)
		}
	}
}

func serve(f func(net.Listener) error, l net.Listener) {
	if err := f(l); err != nil && !stopping.Load() && err != cmux.ErrListenerClosed && err != http.ErrServerClosed {
		log.Fatalf("cmux: a listener stopped: %v", err)
	}
}

// hello answers every request with 200 and the 13-byte body.
func hello(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(body)
}

func acceptLoop(l net.Listener, handle func(net.Conn)) {
	for {
		c, err := l.Accept()
		if err != nil {
			return
		}
		go handle(c)
	}
}

// ssh is the server's SSH handler: its identification line at entry, then the client's line, then close.
func ssh(c net.Conn) {
	defer c.Close()
	if _, err := io.WriteString(c, "SSH-2.0-oneport\r\n"); err != nil {
		return
	}
	_, _ = bufio.NewReader(c).ReadString('\n')
}

// smtp is the server's SMTP handler: the greeting, then 250 to EHLO, 221 to QUIT, 500 to anything else.
func smtp(c net.Conn) {
	defer c.Close()
	if _, err := io.WriteString(c, "220 oneport.test ESMTP\r\n"); err != nil {
		return
	}
	r := bufio.NewReader(c)
	for {
		line, err := r.ReadString('\n')
		if err != nil {
			return
		}
		verb := ""
		if f := strings.Fields(strings.TrimRight(line, "\r\n")); len(f) > 0 {
			verb = strings.ToUpper(f[0])
		}
		switch {
		case strings.HasSuffix(line, "\r\n") && verb == "EHLO":
			_, err = io.WriteString(c, "250 oneport.test\r\n")
		case strings.HasSuffix(line, "\r\n") && verb == "QUIT":
			_, _ = io.WriteString(c, "221 oneport.test closing\r\n")
			return
		default:
			_, err = io.WriteString(c, "500 syntax error, command unrecognized\r\n")
		}
		if err != nil {
			return
		}
	}
}

// collector runs WL7's step for the cmux harness on each SIGUSR1: debug.FreeOSMemory, then HeapInuse.
func collector(sig <-chan os.Signal) {
	for range sig {
		debug.FreeOSMemory()
		var ms runtime.MemStats
		runtime.ReadMemStats(&ms)
		out, _ := json.Marshal(map[string]uint64{"heap_inuse": ms.HeapInuse, "heap_sys": ms.HeapSys, "heap_released": ms.HeapReleased,
			"stack_inuse": ms.StackInuse, "sys": ms.Sys, "num_gc": uint64(ms.NumGC)})
		fmt.Printf("cmux: collector %s\n", out)
	}
}
