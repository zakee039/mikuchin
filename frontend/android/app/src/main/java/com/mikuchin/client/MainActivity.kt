package com.mikuchin.client

import android.annotation.SuppressLint
import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Color
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.net.wifi.WifiInfo
import android.net.wifi.WifiManager
import android.os.Bundle
import android.util.Base64
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

class MainActivity : ComponentActivity() {

    private lateinit var webView: WebView
    private lateinit var secureStore: SecureStore
    private lateinit var connectionProfiles: ConnectionProfiles
    private lateinit var tailscaleController: TailscaleController
    private var fileUploadCallback: ValueCallback<Array<Uri>>? = null
    private val connectGeneration = AtomicInteger(0)
    private val connectExecutor = Executors.newSingleThreadExecutor()
    private var pendingWifiBindId: String? = null

    private val wifiPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        val id = pendingWifiBindId
        pendingWifiBindId = null
        if (id != null) {
            val ssid = if (granted) currentWifiSsid() else null
            val ok = ssid != null && connectionProfiles.bindWifi(id, ssid)
            emitWifiResult(ok, if (ok) "已记住当前 Wi-Fi：$ssid" else
                "无法获取 Wi-Fi 名称。请检查定位服务和位置权限，或继续手动选择入口。")
        }
    }

    private val fileChooserLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        val callback = fileUploadCallback ?: return@registerForActivityResult
        fileUploadCallback = null
        if (result.resultCode != Activity.RESULT_OK) {
            callback.onReceiveValue(null)
            return@registerForActivityResult
        }
        val data = result.data
        val uris = when {
            data?.clipData != null -> {
                val count = data.clipData!!.itemCount
                Array(count) { i -> data.clipData!!.getItemAt(i).uri }
            }
            data?.data != null -> arrayOf(data.data!!)
            else -> null
        }
        callback.onReceiveValue(uris)
    }

    private val shellCssBase64 by lazy {
        val bytes = assets.open("android-shell.css").use { it.readBytes() }
        Base64.encodeToString(bytes, Base64.NO_WRAP)
    }

    private val shellJs by lazy {
        assets.open("android-shell.js").bufferedReader(Charsets.UTF_8).use { it.readText() }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Enforce light system bars
        window.statusBarColor = Color.parseColor("#F8FAFC")
        window.navigationBarColor = Color.parseColor("#FFFFFF")
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = true
            isAppearanceLightNavigationBars = true
        }

        secureStore = SecureStore(applicationContext)
        connectionProfiles = ConnectionProfiles(applicationContext, secureStore)
        tailscaleController = TailscaleController(applicationContext)

        webView = WebView(this)
        webView.setBackgroundColor(Color.parseColor("#F8FAFC"))
        setContentView(webView)

        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false)

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            allowFileAccess = false
            allowContentAccess = true
            @Suppress("DEPRECATION")
            allowFileAccessFromFileURLs = false
            @Suppress("DEPRECATION")
            allowUniversalAccessFromFileURLs = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            useWideViewPort = true
            loadWithOverviewMode = true
        }

        webView.addJavascriptInterface(AndroidBridge(), "MikuchinAndroid")

        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
                super.onPageStarted(view, url, favicon)
                if (isAuthorizedWebUrl(url)) {
                    val key = secureStore.apiKey
                    val latestSessionId = secureStore.latestSessionId
                    val quotedJsonKey = JSONObject.quote(JSONObject.quote(key))
                    val quotedJsonSession = JSONObject.quote(JSONObject.quote(latestSessionId))
                    val preScript = """
                        (function() {
                          try {
                            localStorage.setItem("strata.theme", "light");
                            document.documentElement.dataset.theme = "light";
                            localStorage.setItem("strata.apikey", $quotedJsonKey);
                            if (${latestSessionId.isNotEmpty()}) {
                              localStorage.setItem("strata.session-id", $quotedJsonSession);
                            }
                          } catch (e) {}
                        })();
                    """.trimIndent()
                    view.evaluateJavascript(preScript, null)
                }
            }

            override fun onPageFinished(view: WebView, url: String) {
                super.onPageFinished(view, url)
                if (isAuthorizedWebUrl(url)) {
                    val injectCss = """
                        (function() {
                          document.documentElement.dataset.theme = "light";
                          if (!document.getElementById("mk-android-shell-css")) {
                            var style = document.createElement("style");
                            style.id = "mk-android-shell-css";
                            style.textContent = decodeURIComponent(escape(window.atob("$shellCssBase64")));
                            document.head.appendChild(style);
                          }
                        })();
                    """.trimIndent()
                    view.evaluateJavascript(injectCss, null)
                    view.evaluateJavascript(shellJs, null)
                }
            }

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val targetUrl = request.url?.toString() ?: return true
                if (targetUrl.startsWith("file:///android_asset/login.html")) {
                    return false
                }
                if (isAuthorizedWebUrl(targetUrl)) {
                    return false
                }
                // Block untrusted external pages from loading inside the bridged WebView;
                // open valid external http/https links in the system browser instead.
                if (targetUrl.startsWith("https://") || targetUrl.startsWith("http://")) {
                    try {
                        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(targetUrl)))
                    } catch (_: Exception) {}
                }
                return true
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                webView: WebView,
                filePathCallback: ValueCallback<Array<Uri>>,
                fileChooserParams: FileChooserParams
            ): Boolean {
                fileUploadCallback?.onReceiveValue(null)
                fileUploadCallback = filePathCallback
                return try {
                    fileChooserLauncher.launch(fileChooserParams.createIntent())
                    true
                } catch (e: Exception) {
                    fileUploadCallback = null
                    false
                }
            }
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                webView.evaluateJavascript(
                    """
                    (function() {
                      var sb = document.getElementById("session-sidebar");
                      if (sb && sb.classList.contains("mobile-open")) {
                        document.getElementById("session-backdrop").click();
                        return true;
                      }
                      if (document.body && document.body.dataset.activeTab && document.body.dataset.activeTab !== "chat") {
                        if (typeof showTab === "function") showTab("chat");
                        return true;
                      }
                      return false;
                    })();
                    """.trimIndent()
                ) { handled ->
                    if (handled != "true") {
                        if (webView.canGoBack()) webView.goBack() else finish()
                    }
                }
            }
        })

        // Every launch starts at the native-controlled connection chooser.
        // Its short auto-connect countdown is cancelable by selecting any row.
        showLoginGate()
    }

    override fun onResume() {
        super.onResume()
        if (secureStore.connectionMode == "tailscale") {
            thread {
                val statusJson = tailscaleController.getStatus().toJsonString()
                runOnUiThread {
                    webView.evaluateJavascript("window.onTailscaleStatus && window.onTailscaleStatus(${JSONObject.quote(statusJson)});", null)
                }
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        connectGeneration.incrementAndGet()
        connectExecutor.shutdownNow()
        tailscaleController.stop()
    }

    private fun openAuthUrlInternal(url: String) {
        val trimmed = url.trim()
        if (!trimmed.startsWith("https://login.tailscale.com/")) return
        runOnUiThread {
            try {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(trimmed)))
            } catch (_: Exception) {}
        }
    }

    private fun isAuthorizedWebUrl(url: String): Boolean {
        val origin = extractOrigin(url) ?: return false
        val allowed = tailscaleController.getAuthorizedWebOrigin(secureStore.connectionMode, secureStore.activeEndpoint)
        return allowed.isNotEmpty() && origin.equals(allowed, ignoreCase = true)
    }

    private fun extractOrigin(url: String): String? {
        return try {
            val u = Uri.parse(url)
            val scheme = u.scheme?.lowercase() ?: return null
            val host = u.host?.lowercase() ?: return null
            val port = u.port
            if (port != -1 && !((scheme == "http" && port == 80) || (scheme == "https" && port == 443))) {
                "$scheme://$host:$port"
            } else {
                "$scheme://$host"
            }
        } catch (_: Exception) {
            null
        }
    }

    private fun getCurrentWebViewUrlSafe(): String {
        if (mainLooper.isCurrentThread) {
            return webView.url ?: ""
        }
        val ref = AtomicReference("")
        val latch = CountDownLatch(1)
        runOnUiThread {
            ref.set(webView.url ?: "")
            latch.countDown()
        }
        latch.await(1500, TimeUnit.MILLISECONDS)
        return ref.get()
    }

    private fun isCallerAuthorized(): Boolean {
        val currentUrl = getCurrentWebViewUrlSafe()
        if (currentUrl.startsWith("file:///android_asset/login.html")) {
            return true
        }
        return isAuthorizedWebUrl(currentUrl)
    }

    private fun isChooserPage(): Boolean =
        getCurrentWebViewUrlSafe().substringBefore('?').substringBefore('#') ==
            "file:///android_asset/login.html"

    private fun showLoginGate(manual: Boolean = false) {
        runOnUiThread {
            webView.loadUrl("file:///android_asset/login.html" + if (manual) "?manual=1" else "")
        }
    }

    @Suppress("DEPRECATION")
    private fun currentWifiSsid(): String? {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            != PackageManager.PERMISSION_GRANTED) return null
        return try {
            val network = getSystemService(ConnectivityManager::class.java)
            // The system's active Network may be a VPN (Clash/Mihomo); inspect
            // existing underlying transports too without scanning nearby APs.
            val candidates = listOfNotNull(network.activeNetwork) + network.allNetworks.toList()
            val capabilities = candidates.distinct().mapNotNull { network.getNetworkCapabilities(it) }
                .firstOrNull { it.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) }
                ?: return null
            fun cleaned(raw: String?): String? = raw?.removeSurrounding("\"")?.takeIf {
                it.isNotBlank() && it != WifiManager.UNKNOWN_SSID && it != "<unknown ssid>"
            }
            // Some API 31+ capability snapshots redact SSID even with a Wi-Fi
            // transport. The legacy getter is only a fallback, never a scan.
            cleaned((capabilities.transportInfo as? WifiInfo)?.ssid) ?:
                cleaned((getSystemService(WIFI_SERVICE) as WifiManager).connectionInfo?.ssid)
        } catch (_: Exception) { null }
    }

    private fun emitWifiResult(ok: Boolean, message: String) {
        val snapshot = connectionProfiles.snapshot(currentWifiSsid())
        runOnUiThread {
            webView.evaluateJavascript(
                "window.onWifiMemoryResult && window.onWifiMemoryResult($ok,${JSONObject.quote(message)},$snapshot);", null)
        }
    }

    private fun chooserProgress(id: String, message: String) {
        runOnUiThread {
            webView.evaluateJavascript(
                "window.onEntryProgress && window.onEntryProgress(${JSONObject.quote(id)},${JSONObject.quote(message)});", null)
        }
    }

    private fun chooserFinished(ok: Boolean, message: String) {
        runOnUiThread {
            webView.evaluateJavascript(
                "window.onConnectResult && window.onConnectResult($ok,${JSONObject.quote(message)});", null)
        }
    }

    /** One candidate at a time: tsnet's proxy target is shared across requests. */
    private fun connectCandidate(profile: ConnectionProfile, generation: Int): String? {
        val mode = profile.mode
        val endpoint = profile.endpoint
        val key = connectionProfiles.keyOf(profile)
        try {
            if (generation != connectGeneration.get()) return "连接已取消"
            if (mode == "tailscale") {
                tailscaleController.ensureStarted()
                for (i in 0 until 20) {
                    if (generation != connectGeneration.get()) return "连接已取消"
                    if (tailscaleController.getStatus().state == "Running") break
                    Thread.sleep(500)
                }
                if (tailscaleController.getStatus().state != "Running")
                    return "Tailscale 未就绪，请先完成设备授权"
            }

            // Probe without credentials first. Legacy main exposes /health
            // (HTTP 200); the Native Gateway deliberately protects it and
            // responds with its characteristic 401 JSON. Only after either
            // compatible response do we send this profile's own saved key
            // to /v1/strata/sessions. Never relax Native server auth.
            val health = tailscaleController.openMikuchinConnection(mode, endpoint, "/health", "")
            val healthCode: Int
            val healthChallenge: String?
            try {
                healthCode = health.responseCode
                healthChallenge = if (healthCode == 401) {
                    health.errorStream?.reader(Charsets.UTF_8)?.use { reader ->
                        val buffer = CharArray(2048)
                        val count = reader.read(buffer)
                        if (count > 0) String(buffer, 0, count) else null
                    }
                } else null
            } finally { health.disconnect() }
            if (generation != connectGeneration.get()) return "连接已取消"
            if (!ServerHealthPreflight.accepts(healthCode, healthChallenge)) {
                return "健康检查 HTTP $healthCode（非 Mikuchin Native 鉴权响应）"
            }

            val request = tailscaleController.openMikuchinConnection(
                mode, endpoint, "/v1/strata/sessions", key)
            val code: Int
            val body: String
            try {
                code = request.responseCode
                body = if (code in 200..299) {
                    request.inputStream.bufferedReader(Charsets.UTF_8).use {it.readText()}
                } else ""
            } finally {request.disconnect()}
            if (generation != connectGeneration.get()) return "连接已取消"
            if (code !in 200..299)
                return if (code == 401) "API Key 错误或无权限" else "HTTP $code"

            val sessions = JSONObject(body).optJSONArray("sessions")
                ?: return "目标不是有效的 Mikuchin 会话服务"
            var latestId = ""
            var updated = -1.0
            for (i in 0 until sessions.length()) {
                val entry = sessions.optJSONObject(i) ?: continue
                if (entry.optDouble("updated", 0.0) > updated) {
                    updated = entry.optDouble("updated", 0.0)
                    latestId = entry.optString("id", "")
                }
            }
            val url = tailscaleController.buildWebViewEntryUrl(mode, endpoint)
            if (generation != connectGeneration.get()) return "连接已取消"

            // Persist only after authentication against the intended endpoint.
            secureStore.connectionMode = mode
            secureStore.activeEndpoint = endpoint
            secureStore.apiKey = key
            secureStore.latestSessionId = latestId
            secureStore.isConnected = true
            connectionProfiles.preferredId = profile.id
            runOnUiThread {
                if (generation == connectGeneration.get()) webView.loadUrl(url)
            }
            return null
        } catch (e: Exception) {
            return if (mode == "tailscale") "Tailnet 连接失败：${e.message.orEmpty().take(100)}" else
                "无法连接：${e.message.orEmpty().take(100)}"
        }
    }

    private fun selectProfile(id: String) {
        val generation = connectGeneration.incrementAndGet()
        val chosen = connectionProfiles.byId(id)
        if (chosen == null) {chooserFinished(false, "入口不存在，请重新选择"); return}
        connectExecutor.execute {
            if (generation != connectGeneration.get()) return@execute
            chooserProgress(id, "正在连接 ${chosen.name}…")
            val error = connectCandidate(chosen, generation)
            if (generation == connectGeneration.get() && error != null) chooserFinished(false, error)
        }
    }

    private fun autoConnect(manualRetry: Boolean = false) {
        if (!connectionProfiles.autoEnabled && !manualRetry) return
        val generation = connectGeneration.incrementAndGet()
        connectExecutor.execute {
            val candidates = connectionProfiles.candidates(currentWifiSsid())
            if (candidates.isEmpty()) {
                if (generation == connectGeneration.get()) chooserFinished(false,
                    "没有可安全自动尝试的入口。陌生 Wi-Fi 不会自动访问明文局域网地址；请手动连接或绑定当前 Wi-Fi。")
                return@execute
            }
            for (candidate in candidates) {
                if (generation != connectGeneration.get()) return@execute
                chooserProgress(candidate.id, "正在检测 ${candidate.name}…")
                if (connectCandidate(candidate, generation) == null) return@execute
            }
            if (generation == connectGeneration.get())
                chooserFinished(false, "已尝试所有已保存入口，请手动选择或编辑地址")
        }
    }

    private fun verifyAndOpen(rawEndpoint: String, rawKey: String, fallbackToLogin: Boolean) {
        // Legacy Android settings 'Save & reconnect' still works. Update the
        // explicitly selected entry rather than overwriting other endpoints.
        val current = connectionProfiles.byId(connectionProfiles.preferredId)
        try {
            val profile = connectionProfiles.upsert(current?.id, current?.name ?: "自定义入口",
                secureStore.connectionMode, rawEndpoint, rawKey)
            selectProfile(profile.id)
        } catch (e: IllegalArgumentException) {
            chooserFinished(false, e.message ?: "无效连接地址")
            if (fallbackToLogin) showLoginGate(manual = true)
        }
    }

    inner class AndroidBridge {
        @JavascriptInterface
        fun getConnectionProfiles(): String {
            if (!isChooserPage()) return "{}"
            return connectionProfiles.snapshot(currentWifiSsid())
        }

        @JavascriptInterface
        fun getProfileKey(id: String): String {
            // Profile credentials are only editable on the bundled login page,
            // never exposed to a potentially compromised remote WebView page.
            if (!isChooserPage()) return ""
            return connectionProfiles.byId(id)?.let {connectionProfiles.keyOf(it)} ?: ""
        }

        @JavascriptInterface
        fun saveConnectionProfile(id: String, name: String, mode: String,
                                  endpoint: String, key: String): String {
            if (!isChooserPage()) return "{}"
            return try {
                val profile = connectionProfiles.upsert(id.ifBlank {null}, name, mode, endpoint, key)
                JSONObject().put("ok", true).put("id", profile.id)
                    .put("profiles", JSONObject(connectionProfiles.snapshot(currentWifiSsid()))).toString()
            } catch (e: Exception) {
                JSONObject().put("ok", false).put("error", e.message ?: "保存入口失败").toString()
            }
        }

        @JavascriptInterface
        fun deleteConnectionProfile(id: String): String {
            if (!isChooserPage()) return "{}"
            connectGeneration.incrementAndGet()
            connectionProfiles.delete(id)
            return connectionProfiles.snapshot(currentWifiSsid())
        }

        @JavascriptInterface
        fun setConnectionAutoEnabled(enabled: Boolean) {
            if (!isChooserPage()) return
            connectionProfiles.autoEnabled = enabled
            if (!enabled) connectGeneration.incrementAndGet()
        }

        @JavascriptInterface
        fun connectProfile(id: String) {
            if (!isChooserPage()) return
            selectProfile(id)
        }

        @JavascriptInterface
        fun startAutoConnect() {
            if (!isChooserPage()) return
            autoConnect()
        }

        @JavascriptInterface
        fun retryAutoConnect() {
            if (!isChooserPage()) return
            autoConnect(manualRetry = true)
        }

        @JavascriptInterface
        fun cancelAutoConnect() {
            if (!isChooserPage()) return
            connectGeneration.incrementAndGet()
        }

        @JavascriptInterface
        fun bindCurrentWifi(id: String) {
            if (!isChooserPage()) return
            if (connectionProfiles.byId(id) == null) return
            runOnUiThread {
                if (ContextCompat.checkSelfPermission(this@MainActivity,
                        Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
                    pendingWifiBindId = id
                    wifiPermission.launch(Manifest.permission.ACCESS_FINE_LOCATION)
                } else {
                    val wifi = currentWifiSsid()
                    val ok = wifi != null && connectionProfiles.bindWifi(id, wifi)
                    emitWifiResult(ok, if (ok) "已绑定 Wi-Fi：$wifi" else
                        "当前无法读取 SSID，请检查 Wi-Fi、定位权限及系统定位开关")
                }
            }
        }

        @JavascriptInterface
        fun clearWifiMemory(id: String): String {
            if (!isChooserPage()) return "{}"
            connectionProfiles.clearWifi(id)
            return connectionProfiles.snapshot(currentWifiSsid())
        }

        @JavascriptInterface
        fun showConnectionChooser() {
            if (!isCallerAuthorized()) return
            connectGeneration.incrementAndGet()
            showLoginGate(manual = true)
        }

        @JavascriptInterface
        fun getSavedEndpoint(): String {
            if (!isCallerAuthorized()) return ""
            return secureStore.activeEndpoint
        }

        @JavascriptInterface
        fun getSavedKey(): String {
            if (!isCallerAuthorized()) return ""
            return secureStore.apiKey
        }

        @JavascriptInterface
        fun getConnectionMode(): String {
            if (!isCallerAuthorized()) return "direct"
            return secureStore.connectionMode
        }

        @JavascriptInterface
        fun setConnectionMode(mode: String) {
            if (!isCallerAuthorized()) return
            val normalized = if (mode == "tailscale") "tailscale" else "direct"
            secureStore.connectionMode = normalized
            if (normalized == "tailscale") {
                thread {
                    tailscaleController.ensureStarted()
                    val statusJson = tailscaleController.getStatus().toJsonString()
                    runOnUiThread {
                        webView.evaluateJavascript("window.onTailscaleStatus && window.onTailscaleStatus(${JSONObject.quote(statusJson)});", null)
                    }
                }
            }
        }

        @JavascriptInterface
        fun getTailscaleStatus(): String {
            if (!isCallerAuthorized()) return "{}"
            return tailscaleController.getStatus().toJsonString()
        }

        @JavascriptInterface
        fun startTailscaleLogin(): String {
            if (!isCallerAuthorized()) return "{}"
            secureStore.connectionMode = "tailscale"
            val currentSt = tailscaleController.getStatus()
            if (currentSt.authUrl.startsWith("https://login.tailscale.com/")) {
                openAuthUrlInternal(currentSt.authUrl)
                return currentSt.toJsonString()
            }
            thread {
                val initSt = tailscaleController.startInteractiveLogin()
                var opened = false
                if (initSt.authUrl.startsWith("https://login.tailscale.com/")) {
                    opened = true
                    openAuthUrlInternal(initSt.authUrl)
                }
                val initJson = initSt.toJsonString()
                runOnUiThread {
                    webView.evaluateJavascript("window.onTailscaleStatus && window.onTailscaleStatus(${JSONObject.quote(initJson)});", null)
                }
                for (i in 0 until 45) {
                    Thread.sleep(400)
                    val st = tailscaleController.getStatus()
                    val pubJson = st.toJsonString()
                    runOnUiThread {
                        webView.evaluateJavascript("window.onTailscaleStatus && window.onTailscaleStatus(${JSONObject.quote(pubJson)});", null)
                    }
                    if (!opened && st.authUrl.startsWith("https://login.tailscale.com/")) {
                        opened = true
                        openAuthUrlInternal(st.authUrl)
                    }
                    if (st.state == "Running") break
                }
            }
            return TailscaleStatus(state = "Starting", hostname = currentSt.hostname).toJsonString()
        }

        @JavascriptInterface
        fun openAuthUrl(url: String) {
            if (!isCallerAuthorized()) return
            openAuthUrlInternal(url)
        }

        @JavascriptInterface
        fun reconnectTailscale(): String {
            if (!isCallerAuthorized()) return "{}"
            return tailscaleController.reconnect().toJsonString()
        }

        @JavascriptInterface
        fun logoutTailscale(): String {
            if (!isCallerAuthorized()) return "{}"
            return tailscaleController.logout().toJsonString()
        }

        @JavascriptInterface
        fun connectEndpoint(endpoint: String, key: String) {
            if (!isCallerAuthorized()) return
            verifyAndOpen(endpoint, key, fallbackToLogin = false)
        }

        @JavascriptInterface
        fun disconnect() {
            if (!isCallerAuthorized()) return
            connectGeneration.incrementAndGet()
            secureStore.isConnected = false
            showLoginGate(manual = true)
        }
    }
}
