package tsnetbridge

import (
	"context"
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httputil"
	"net/netip"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	_ "golang.org/x/mobile/bind"
	"tailscale.com/ipn"
	"tailscale.com/net/netmon"
	"tailscale.com/tsnet"
)

func init() {
	// Android 11-15 (including HyperOS on Redmi K80 Pro) blocks netlink RTM_GETLINK
	// via SELinux, causing standard net.Interfaces() to fail with permission denied.
	// Register a fallback interface getter that discovers the active local IP via UDP socket.
	netmon.RegisterInterfaceGetter(androidSafeInterfaces)
}

func androidSafeInterfaces() ([]netmon.Interface, error) {
	stdIfs, err := net.Interfaces()
	if err == nil && len(stdIfs) > 0 {
		var out []netmon.Interface
		hasNonLoopback := false
		for _, iface := range stdIfs {
			ifaceCopy := iface
			addrs, addrErr := iface.Addrs()
			if addrErr != nil || addrs == nil {
				addrs = []net.Addr{}
			}
			if iface.Flags&net.FlagUp != 0 && iface.Flags&net.FlagLoopback == 0 && len(addrs) > 0 {
				hasNonLoopback = true
				notifyDefaultRouteInterface(iface.Name)
			}
			out = append(out, netmon.Interface{
				Interface: &ifaceCopy,
				AltAddrs:  addrs,
			})
		}
		if hasNonLoopback {
			return out, nil
		}
	}

	var result []netmon.Interface
	loIP := net.ParseIP("127.0.0.1")
	result = append(result, netmon.Interface{
		Interface: &net.Interface{
			Index:        1,
			MTU:          65536,
			Name:         "lo",
			HardwareAddr: nil,
			Flags:        net.FlagUp | net.FlagLoopback | net.FlagRunning,
		},
		AltAddrs: []net.Addr{&net.IPNet{IP: loIP, Mask: net.CIDRMask(8, 32)}},
	})

	conn, dialErr := net.DialTimeout("udp4", "223.5.5.5:53", 1500*time.Millisecond)
	if dialErr == nil {
		defer conn.Close()
		if udpAddr, ok := conn.LocalAddr().(*net.UDPAddr); ok && udpAddr.IP != nil {
			ip4 := udpAddr.IP.To4()
			if ip4 != nil {
				notifyDefaultRouteInterface("wlan0")
				result = append(result, netmon.Interface{
					Interface: &net.Interface{
						Index:        2,
						MTU:          1420,
						Name:         "wlan0",
						HardwareAddr: net.HardwareAddr{0x02, 0x00, 0x00, ip4[1], ip4[2], ip4[3]},
						Flags:        net.FlagUp | net.FlagBroadcast | net.FlagMulticast | net.FlagRunning,
					},
					AltAddrs: []net.Addr{&net.IPNet{IP: ip4, Mask: net.CIDRMask(24, 32)}},
				})
			}
		}
	}
	return result, nil
}

type StatusInfo struct {
	State         string `json:"state"`
	AuthURL       string `json:"authUrl"`
	TailscaleIP   string `json:"tailscaleIp"`
	Hostname      string `json:"hostname"`
	SocksPort     int    `json:"socksPort"`
	HttpProxyPort int    `json:"httpProxyPort"`
	ProxyToken    string `json:"proxyToken"`
	Target        string `json:"target"`
	Error         string `json:"error"`
}

var (
	mu            sync.Mutex
	startMu       sync.Mutex
	srv           *tsnet.Server
	stateDir      string
	nodeHostname  string
	socksListener net.Listener
	httpListener  net.Listener
	socksPort     int
	httpProxyPort int
	proxyToken    string
	targetAddr    string
	targetScheme  string
	lastAuthURL   string
	lastErr       string
	starting      bool
	running       bool
	testDialer    func(ctx context.Context, network, addr string) (net.Conn, error)
)

func generateToken() string {
	b := make([]byte, 24)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// Sanitized logger that never writes private keys, tokens, or auth keys to Android logcat.
func sanitizedLogf(format string, args ...any) {
	defer func() { _ = recover() }()
	msg := fmt.Sprintf(format, args...)
	lower := strings.ToLower(msg)
	if strings.Contains(lower, "private") || strings.Contains(lower, "secret") ||
		strings.Contains(lower, "bearer") || strings.Contains(lower, "authkey") {
		return
	}
	if strings.Contains(msg, "https://login.tailscale.com/") {
		for _, field := range strings.Fields(msg) {
			if strings.HasPrefix(field, "https://login.tailscale.com/") {
				mu.Lock()
				lastAuthURL = strings.TrimRight(field, ".,;)\"'")
				mu.Unlock()
			}
		}
	}
}

// Start initializes the user-space tsnet node, SOCKS5 server (127.0.0.1:0), and local HTTP reverse proxy (127.0.0.1:0).
func Start(dir string, hostname string) (retErr error) {
	defer func() {
		if r := recover(); r != nil {
			errMsg := fmt.Sprintf("tsnet start panic: %v", r)
			mu.Lock()
			lastErr = errMsg
			starting = false
			running = false
			srv = nil
			mu.Unlock()
			retErr = errors.New(errMsg)
		}
	}()

	startMu.Lock()
	defer startMu.Unlock()

	mu.Lock()
	if (running && srv != nil) || starting {
		mu.Unlock()
		return nil
	}
	if hostname == "" {
		hostname = "mikuchin-android"
	}
	stateDir = filepath.Join(dir, "tsnet-node")
	logsDir := filepath.Join(stateDir, "logs")
	cacheDir := filepath.Join(stateDir, "cache")
	tmpDir := filepath.Join(stateDir, "tmp")
	for _, d := range []string{stateDir, logsDir, cacheDir, tmpDir} {
		if err := os.MkdirAll(d, 0700); err != nil {
			lastErr = err.Error()
			mu.Unlock()
			return err
		}
	}
	// Android does not set HOME, XDG_CACHE_HOME, TMPDIR, or TS_LOGS_DIR by default,
	// which causes tailscale.com/logpolicy.LogsDir to panic with "no safe place found to store log state".
	_ = os.Setenv("TS_LOGS_DIR", logsDir)
	_ = os.Setenv("HOME", stateDir)
	_ = os.Setenv("XDG_CACHE_HOME", cacheDir)
	_ = os.Setenv("XDG_CONFIG_HOME", stateDir)
	_ = os.Setenv("TMPDIR", tmpDir)

	nodeHostname = hostname
	if proxyToken == "" {
		proxyToken = generateToken()
	}
	lastErr = ""
	starting = true
	mu.Unlock()

	s := &tsnet.Server{
		Dir:       stateDir,
		Hostname:  nodeHostname,
		Ephemeral: false,
		Logf:      sanitizedLogf,
		UserLogf:  sanitizedLogf,
	}

	if err := s.Start(); err != nil {
		mu.Lock()
		lastErr = err.Error()
		starting = false
		running = false
		srv = nil
		mu.Unlock()
		return err
	}

	if err := startLocalProxies(); err != nil {
		_ = s.Close()
		mu.Lock()
		lastErr = err.Error()
		starting = false
		running = false
		srv = nil
		mu.Unlock()
		return err
	}

	mu.Lock()
	srv = s
	starting = false
	running = true
	mu.Unlock()

	go watchBusLoop(s)
	return nil
}

func watchBusLoop(s *tsnet.Server) {
	defer func() { _ = recover() }()
	lc, err := s.LocalClient()
	if err != nil {
		return
	}
	ctx := context.Background()
	watcher, err := lc.WatchIPNBus(ctx, ipn.NotifyInitialState|ipn.NotifyNoPrivateKeys)
	if err != nil {
		return
	}
	defer watcher.Close()
	for {
		n, err := watcher.Next()
		if err != nil {
			return
		}
		if n.BrowseToURL != nil && *n.BrowseToURL != "" {
			mu.Lock()
			lastAuthURL = *n.BrowseToURL
			mu.Unlock()
		}
		if n.ErrMessage != nil && *n.ErrMessage != "" {
			mu.Lock()
			lastErr = *n.ErrMessage
			mu.Unlock()
		}
	}
}

// StartLogin initiates interactive OAuth login if not already authenticated, and returns current status JSON.
func StartLogin() (res string) {
	defer func() {
		if r := recover(); r != nil {
			mu.Lock()
			lastErr = fmt.Sprintf("startLogin panic: %v", r)
			mu.Unlock()
			res = GetStatusJSON()
		}
	}()
	go func() {
		defer func() { _ = recover() }()
		// Wait if Start() is currently in progress.
		startMu.Lock()
		startMu.Unlock()

		mu.Lock()
		s := srv
		isRunning := running
		mu.Unlock()
		if !isRunning || s == nil {
			return
		}
		lc, err := s.LocalClient()
		if err != nil {
			mu.Lock()
			lastErr = err.Error()
			mu.Unlock()
			return
		}
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		st, err := lc.StatusWithoutPeers(ctx)
		if err == nil && st.BackendState == "Running" {
			return
		}
		if err == nil && st.AuthURL != "" {
			mu.Lock()
			lastAuthURL = st.AuthURL
			mu.Unlock()
		}
		_, _ = lc.EditPrefs(ctx, &ipn.MaskedPrefs{
			WantRunningSet: true,
			LoggedOutSet:   true,
			Prefs:          ipn.Prefs{WantRunning: true, LoggedOut: false},
		})
		_ = lc.StartLoginInteractive(ctx)
		for i := 0; i < 40; i++ {
			time.Sleep(350 * time.Millisecond)
			st, err := lc.StatusWithoutPeers(ctx)
			if err == nil {
				if st.AuthURL != "" {
					mu.Lock()
					lastAuthURL = st.AuthURL
					mu.Unlock()
					return
				}
				if st.BackendState == "Running" {
					return
				}
			}
		}
	}()
	return GetStatusJSON()
}

// SetTarget configures the Tailnet Mikuchin endpoint (e.g. "100.64.0.1:8000" or "http://100.64.0.1:8000").
func SetTarget(raw string) error {
	u := strings.TrimSpace(raw)
	if u == "" {
		return errors.New("empty target")
	}
	if !strings.HasPrefix(strings.ToLower(u), "http://") && !strings.HasPrefix(strings.ToLower(u), "https://") {
		u = "http://" + u
	}
	parsed, err := url.Parse(u)
	if err != nil || parsed.Host == "" {
		return fmt.Errorf("invalid target endpoint: %s", raw)
	}
	hostPort := parsed.Host
	if !strings.Contains(hostPort, ":") {
		if parsed.Scheme == "https" {
			hostPort += ":443"
		} else {
			hostPort += ":80"
		}
	}
	mu.Lock()
	targetAddr = hostPort
	targetScheme = parsed.Scheme
	mu.Unlock()
	return nil
}

// GetStatusJSON returns the current tsnet state, AuthURL, Tailscale IP, and local proxy ports.
func GetStatusJSON() (res string) {
	defer func() {
		if r := recover(); r != nil {
			b, _ := json.Marshal(StatusInfo{
				State:    "Error",
				Hostname: "mikuchin-android",
				Error:    fmt.Sprintf("status panic: %v", r),
			})
			res = string(b)
		}
	}()

	mu.Lock()
	s := srv
	isStarting := starting
	isRunning := running
	authURL := lastAuthURL
	errMsg := lastErr
	hName := nodeHostname
	sPort := socksPort
	hPort := httpProxyPort
	pToken := proxyToken
	tgt := targetAddr
	mu.Unlock()

	if hName == "" {
		hName = "mikuchin-android"
	}

	info := StatusInfo{
		State:         "Stopped",
		AuthURL:       authURL,
		Hostname:      hName,
		SocksPort:     sPort,
		HttpProxyPort: hPort,
		ProxyToken:    pToken,
		Target:        tgt,
		Error:         errMsg,
	}
	if isStarting {
		info.State = "Starting"
		b, _ := json.Marshal(info)
		return string(b)
	}
	if !isRunning || s == nil {
		if errMsg != "" {
			info.State = "Error"
		}
		b, _ := json.Marshal(info)
		return string(b)
	}

	lc, err := s.LocalClient()
	if err != nil {
		info.State = "Error"
		info.Error = err.Error()
		b, _ := json.Marshal(info)
		return string(b)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	st, err := lc.StatusWithoutPeers(ctx)
	if err != nil {
		info.State = "Starting"
		b, _ := json.Marshal(info)
		return string(b)
	}

	if st.AuthURL != "" {
		info.AuthURL = st.AuthURL
		mu.Lock()
		lastAuthURL = st.AuthURL
		mu.Unlock()
	}

	var tsIP string
	for _, ip := range st.TailscaleIPs {
		if ip.Is4() {
			tsIP = ip.String()
			break
		}
	}
	if tsIP == "" && len(st.TailscaleIPs) > 0 {
		tsIP = st.TailscaleIPs[0].String()
	}
	info.TailscaleIP = tsIP

	switch st.BackendState {
	case "Running":
		if tsIP != "" {
			info.State = "Running"
			info.AuthURL = ""
		} else {
			info.State = "Starting"
		}
	case "NeedsLogin", "NeedsMachineAuth":
		info.State = "NeedsLogin"
	case "Starting", "NoState":
		if info.AuthURL != "" {
			info.State = "NeedsLogin"
		} else {
			info.State = "Starting"
		}
	default:
		info.State = st.BackendState
	}

	b, _ := json.Marshal(info)
	return string(b)
}

// Logout logs out the current Tailscale node and clears session auth URL.
func Logout() (retErr error) {
	defer func() {
		if r := recover(); r != nil {
			retErr = fmt.Errorf("logout panic: %v", r)
		}
	}()
	mu.Lock()
	s := srv
	isRunning := running
	lastAuthURL = ""
	mu.Unlock()
	if !isRunning || s == nil {
		return nil
	}
	lc, err := s.LocalClient()
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	return lc.Logout(ctx)
}

// Reconnect forces tsnet to re-establish its control/data plane connection.
func Reconnect() (retErr error) {
	defer func() {
		if r := recover(); r != nil {
			retErr = fmt.Errorf("reconnect panic: %v", r)
		}
	}()
	mu.Lock()
	s := srv
	isStarting := starting
	isRunning := running
	dir := stateDir
	host := nodeHostname
	mu.Unlock()
	if isStarting {
		return nil
	}
	if !isRunning || s == nil {
		if dir != "" {
			return Start(filepath.Dir(dir), host)
		}
		return nil
	}
	lc, err := s.LocalClient()
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	defer cancel()
	_, err = lc.EditPrefs(ctx, &ipn.MaskedPrefs{
		WantRunningSet: true,
		Prefs:          ipn.Prefs{WantRunning: true},
	})
	return err
}

// Stop shuts down local proxies and the tsnet server.
func Stop() {
	defer func() { _ = recover() }()
	mu.Lock()
	s := srv
	sl := socksListener
	hl := httpListener
	srv = nil
	socksListener = nil
	httpListener = nil
	socksPort = 0
	httpProxyPort = 0
	starting = false
	running = false
	mu.Unlock()

	if sl != nil {
		_ = sl.Close()
	}
	if hl != nil {
		_ = hl.Close()
	}
	if s != nil {
		_ = s.Close()
	}
}

func startLocalProxies() error {
	mu.Lock()
	if socksListener != nil && httpListener != nil {
		mu.Unlock()
		return nil
	}
	mu.Unlock()

	// 1. Local SOCKS5 server bound strictly to 127.0.0.1:0
	sl, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	sPort := sl.Addr().(*net.TCPAddr).Port

	// 2. Local HTTP Reverse Proxy bound strictly to 127.0.0.1:0
	hl, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		_ = sl.Close()
		return err
	}
	hPort := hl.Addr().(*net.TCPAddr).Port

	mu.Lock()
	socksListener = sl
	httpListener = hl
	socksPort = sPort
	httpProxyPort = hPort
	mu.Unlock()

	go serveSocks5(sl)
	go serveHttpReverseProxy(hl)
	return nil
}

// Minimal RFC 1928 SOCKS5 server dialing exclusively into the user-space Tailnet.
func serveSocks5(l net.Listener) {
	for {
		conn, err := l.Accept()
		if err != nil {
			return
		}
		go handleSocks5Conn(conn)
	}
}

func handleSocks5Conn(c net.Conn) {
	defer c.Close()
	_ = c.SetDeadline(time.Now().Add(15 * time.Second))

	hdr := make([]byte, 2)
	if _, err := io.ReadFull(c, hdr); err != nil || hdr[0] != 0x05 {
		return
	}
	methods := make([]byte, int(hdr[1]))
	if _, err := io.ReadFull(c, methods); err != nil {
		return
	}
	// No-auth on 127.0.0.1
	if _, err := c.Write([]byte{0x05, 0x00}); err != nil {
		return
	}

	req := make([]byte, 4)
	if _, err := io.ReadFull(c, req); err != nil || req[0] != 0x05 || req[1] != 0x01 {
		_, _ = c.Write([]byte{0x05, 0x07, 0x00, 0x01, 0, 0, 0, 0, 0, 0})
		return
	}

	var host string
	switch req[3] {
	case 0x01: // IPv4
		ip := make([]byte, 4)
		if _, err := io.ReadFull(c, ip); err != nil {
			return
		}
		host = net.IP(ip).String()
	case 0x03: // Domain
		lb := make([]byte, 1)
		if _, err := io.ReadFull(c, lb); err != nil {
			return
		}
		dom := make([]byte, int(lb[0]))
		if _, err := io.ReadFull(c, dom); err != nil {
			return
		}
		host = string(dom)
	case 0x04: // IPv6
		ip := make([]byte, 16)
		if _, err := io.ReadFull(c, ip); err != nil {
			return
		}
		host = net.IP(ip).String()
	default:
		return
	}

	pb := make([]byte, 2)
	if _, err := io.ReadFull(c, pb); err != nil {
		return
	}
	port := binary.BigEndian.Uint16(pb)
	dest := net.JoinHostPort(host, fmt.Sprintf("%d", port))

	mu.Lock()
	s := srv
	td := testDialer
	mu.Unlock()
	if s == nil && td == nil {
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
	var remote net.Conn
	var err error
	if td != nil {
		remote, err = td(ctx, "tcp", dest)
	} else {
		remote, err = s.Dial(ctx, "tcp", dest)
	}
	cancel()
	if err != nil {
		_, _ = c.Write([]byte{0x05, 0x04, 0x00, 0x01, 0, 0, 0, 0, 0, 0})
		return
	}
	defer remote.Close()

	_ = c.SetDeadline(time.Time{})
	if _, err := c.Write([]byte{0x05, 0x00, 0x00, 0x01, 127, 0, 0, 1, 0, 0}); err != nil {
		return
	}

	done := make(chan struct{}, 2)
	go func() {
		_, _ = io.Copy(remote, c)
		done <- struct{}{}
	}()
	go func() {
		_, _ = io.Copy(c, remote)
		done <- struct{}{}
	}()
	<-done
}

// Local HTTP reverse proxy over tsnet.Dial with instant SSE flushing (FlushInterval: -1)
// and session token verification to block cross-app access on 127.0.0.1.
func serveHttpReverseProxy(l net.Listener) {
	transport := &http.Transport{
		DialContext: func(ctx context.Context, network, addr string) (net.Conn, error) {
			mu.Lock()
			s := srv
			td := testDialer
			allowedTarget := targetAddr
			mu.Unlock()
			if s == nil && td == nil {
				return nil, errors.New("tailscale server not running")
			}
			// Restrict outgoing connections solely to the configured Mikuchin target
			if allowedTarget != "" && addr != allowedTarget {
				return nil, fmt.Errorf("blocked proxy connection to unauthorized target %s", addr)
			}
			if ip, _, err := net.SplitHostPort(addr); err == nil {
				if parsedIP, err := netip.ParseAddr(ip); err == nil && parsedIP.IsLoopback() {
					return nil, errors.New("loopback target forbidden in tailscale proxy")
				}
			}
			if td != nil {
				return td(ctx, "tcp", addr)
			}
			return s.Dial(ctx, "tcp", addr)
		},
		DisableCompression: true, // Preserve raw SSE stream chunks without buffering
		MaxIdleConns:       32,
		IdleConnTimeout:    60 * time.Second,
	}

	proxy := &httputil.ReverseProxy{
		Director: func(req *http.Request) {
			mu.Lock()
			tgt := targetAddr
			scheme := targetScheme
			mu.Unlock()
			if scheme == "" {
				scheme = "http"
			}
			req.URL.Scheme = scheme
			req.URL.Host = tgt
			req.Host = tgt
			if req.Header.Get("Origin") != "" {
				req.Header.Set("Origin", scheme+"://"+tgt)
			}
			if req.Header.Get("Referer") != "" {
				req.Header.Set("Referer", scheme+"://"+tgt+"/")
			}
			req.Header.Del("X-Mikuchin-Proxy-Token")
		},
		Transport:     transport,
		FlushInterval: -1, // Immediate flush for SSE streaming (/v1/chat/completions)
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			w.Header().Set("Content-Type", "application/json; charset=utf-8")
			w.WriteHeader(http.StatusBadGateway)
			_, _ = fmt.Fprintf(w, `{"error":{"message":"Tailscale 连接目标不可达: %s"}}`, strings.ReplaceAll(err.Error(), `"`, `'`))
		},
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/__mk_entry", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		expected := proxyToken
		mu.Unlock()
		given := r.URL.Query().Get("token")
		if expected == "" || given != expected {
			http.Error(w, "Forbidden", http.StatusForbidden)
			return
		}
		http.SetCookie(w, &http.Cookie{
			Name:     "mk_proxy_token",
			Value:    expected,
			Path:     "/",
			HttpOnly: true,
			SameSite: http.SameSiteLaxMode,
		})
		http.Redirect(w, r, "/", http.StatusTemporaryRedirect)
	})

	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		expected := proxyToken
		tgt := targetAddr
		mu.Unlock()

		if tgt == "" {
			http.Error(w, "Target not configured", http.StatusBadRequest)
			return
		}

		// Verify token from Header (Kotlin native requests) or Cookie (WebView requests)
		authorized := false
		if r.Header.Get("X-Mikuchin-Proxy-Token") == expected {
			authorized = true
		} else if c, err := r.Cookie("mk_proxy_token"); err == nil && c.Value == expected {
			authorized = true
		}
		if !authorized {
			http.Error(w, "Unauthorized local proxy access", http.StatusForbidden)
			return
		}

		proxy.ServeHTTP(w, r)
	})

	server := &http.Server{
		Handler:           mux,
		ReadHeaderTimeout: 15 * time.Second,
	}
	_ = server.Serve(l)
}
