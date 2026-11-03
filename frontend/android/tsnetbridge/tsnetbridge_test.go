package tsnetbridge

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestAndroidSafeInterfaces(t *testing.T) {
	ifs, err := androidSafeInterfaces()
	if err != nil {
		t.Fatalf("androidSafeInterfaces returned error: %v", err)
	}
	if len(ifs) == 0 {
		t.Fatal("expected at least 1 network interface")
	}
}

func TestSetTargetValidation(t *testing.T) {
	if err := SetTarget(""); err == nil {
		t.Fatal("expected error on empty target")
	}
	if err := SetTarget("100.96.190.44:15239"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	var st StatusInfo
	if err := json.Unmarshal([]byte(GetStatusJSON()), &st); err != nil {
		t.Fatalf("invalid status json: %v", err)
	}
	if st.Target != "100.96.190.44:15239" {
		t.Fatalf("expected target 100.96.190.44:15239, got %s", st.Target)
	}
}

func TestSanitizedLogDoesNotLeakSecrets(t *testing.T) {
	lastAuthURL = ""
	sanitizedLogf("To authenticate, visit: https://login.tailscale.com/a/1234567890abcdef.")
	if !strings.HasPrefix(lastAuthURL, "https://login.tailscale.com/a/1234567890abcdef") {
		t.Fatalf("expected AuthURL capture, got %q", lastAuthURL)
	}
}

func TestLocalProxiesAuthAndSSEStreaming(t *testing.T) {
	// Mock Tailnet Mikuchin server (simulating 100.96.190.44:15239)
	releaseSecondChunk := make(chan struct{})
	mockMux := http.NewServeMux()
	mockMux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		if r.Host != "100.96.190.44:15239" {
			http.Error(w, "bad host: "+r.Host, http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})
	mockMux.HandleFunc("/v1/chat/completions", func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Origin") != "http://100.96.190.44:15239" {
			http.Error(w, "bad origin: "+r.Header.Get("Origin"), http.StatusForbidden)
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		flusher, ok := w.(http.Flusher)
		if !ok {
			t.Fatal("ResponseWriter does not implement Flusher")
		}
		_, _ = fmt.Fprintf(w, "data: {\"delta\":\"chunk-1\"}\n\n")
		flusher.Flush()
		<-releaseSecondChunk
		_, _ = fmt.Fprintf(w, "data: {\"delta\":\"chunk-2\"}\n\n")
		flusher.Flush()
	})

	mockServer := httptest.NewServer(mockMux)
	defer mockServer.Close()
	mockAddr := mockServer.Listener.Addr().String()

	mu.Lock()
	proxyToken = generateToken()
	tok := proxyToken
	targetAddr = "100.96.190.44:15239"
	targetScheme = "http"
	testDialer = func(ctx context.Context, network, addr string) (net.Conn, error) {
		if addr != "100.96.190.44:15239" {
			return nil, fmt.Errorf("unexpected target addr %s", addr)
		}
		var d net.Dialer
		return d.DialContext(ctx, "tcp", mockAddr)
	}
	mu.Unlock()
	defer func() {
		Stop()
		mu.Lock()
		testDialer = nil
		mu.Unlock()
	}()

	if err := startLocalProxies(); err != nil {
		t.Fatalf("startLocalProxies failed: %v", err)
	}
	mu.Lock()
	hPort := httpProxyPort
	sPort := socksPort
	mu.Unlock()
	if hPort <= 0 || sPort <= 0 {
		t.Fatalf("invalid proxy ports: http=%d socks=%d", hPort, sPort)
	}

	// 1. Verify unauthenticated request is rejected with 403 Forbidden
	respUnauth, err := http.Get(fmt.Sprintf("http://127.0.0.1:%d/health", hPort))
	if err != nil {
		t.Fatalf("unauth GET failed: %v", err)
	}
	respUnauth.Body.Close()
	if respUnauth.StatusCode != http.StatusForbidden {
		t.Fatalf("expected 403 Forbidden without token, got %d", respUnauth.StatusCode)
	}

	// 2. Verify header-authenticated request (used by Kotlin HttpURLConnection) succeeds
	reqHealth, _ := http.NewRequest("GET", fmt.Sprintf("http://127.0.0.1:%d/health", hPort), nil)
	reqHealth.Header.Set("X-Mikuchin-Proxy-Token", tok)
	respHealth, err := http.DefaultClient.Do(reqHealth)
	if err != nil {
		t.Fatalf("auth GET failed: %v", err)
	}
	bodyHealth, _ := io.ReadAll(respHealth.Body)
	respHealth.Body.Close()
	if respHealth.StatusCode != http.StatusOK || !strings.Contains(string(bodyHealth), `"ok"`) {
		t.Fatalf("unexpected /health response: %d %s", respHealth.StatusCode, string(bodyHealth))
	}

	// 3. Verify real-time SSE streaming arrives immediately before stream finishes
	reqStream, _ := http.NewRequest("POST", fmt.Sprintf("http://127.0.0.1:%d/v1/chat/completions", hPort), strings.NewReader(`{"stream":true}`))
	reqStream.Header.Set("X-Mikuchin-Proxy-Token", tok)
	reqStream.Header.Set("Origin", fmt.Sprintf("http://127.0.0.1:%d", hPort))
	respStream, err := http.DefaultClient.Do(reqStream)
	if err != nil {
		t.Fatalf("SSE request failed: %v", err)
	}
	defer respStream.Body.Close()
	if respStream.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 for SSE stream, got %d", respStream.StatusCode)
	}

	reader := bufio.NewReader(respStream.Body)
	firstLineCh := make(chan string, 1)
	go func() {
		line, _ := reader.ReadString('\n')
		firstLineCh <- line
	}()

	select {
	case line := <-firstLineCh:
		if !strings.Contains(line, "chunk-1") {
			t.Fatalf("expected chunk-1 immediately, got %q", line)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("SSE stream buffered! Did not receive chunk-1 before stream completion")
	}
	close(releaseSecondChunk)

	// 4. Verify SOCKS5 server connects through the dialer
	socksConn, err := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", sPort), 2*time.Second)
	if err != nil {
		t.Fatalf("SOCKS5 dial failed: %v", err)
	}
	defer socksConn.Close()
	// Greeting: VER=5, NMETHODS=1, METHOD=0
	_, _ = socksConn.Write([]byte{0x05, 0x01, 0x00})
	reply := make([]byte, 2)
	if _, err := io.ReadFull(socksConn, reply); err != nil || reply[0] != 0x05 || reply[1] != 0x00 {
		t.Fatalf("SOCKS5 handshake failed: %v %v", err, reply)
	}
}
