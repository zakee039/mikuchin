package com.mikuchin.client

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.net.Uri
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
import androidx.core.view.WindowCompat
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread

class MainActivity : ComponentActivity() {

    private lateinit var webView: WebView
    private lateinit var secureStore: SecureStore
    private lateinit var tailscaleController: TailscaleController
    private var fileUploadCallback: ValueCallback<Array<Uri>>? = null

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

        val savedMode = secureStore.connectionMode
        val savedEndpoint = secureStore.activeEndpoint
        val savedKey = secureStore.apiKey
        val wasConnected = secureStore.isConnected

        if (savedMode == "tailscale") {
            thread {
                tailscaleController.ensureStarted()
                if (savedEndpoint.isNotEmpty()) {
                    tailscaleController.setTargetEndpoint(savedEndpoint)
                }
                if (wasConnected && savedEndpoint.isNotEmpty()) {
                    // Wait up to 10s for persisted Tailscale node state to reach Running
                    for (i in 0 until 20) {
                        if (tailscaleController.getStatus().state == "Running") break
                        Thread.sleep(500)
                    }
                    verifyAndOpen(savedEndpoint, savedKey, fallbackToLogin = true)
                } else {
                    showLoginGate()
                }
            }
        } else {
            if (wasConnected && savedEndpoint.isNotEmpty()) {
                verifyAndOpen(savedEndpoint, savedKey, fallbackToLogin = true)
            } else {
                showLoginGate()
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        tailscaleController.stop()
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

    private fun showLoginGate() {
        runOnUiThread {
            webView.loadUrl("file:///android_asset/login.html")
        }
    }

    private fun verifyAndOpen(rawEndpoint: String, rawKey: String, fallbackToLogin: Boolean) {
        val endpoint = rawEndpoint.trim()
        val key = rawKey.trim()
        val mode = secureStore.connectionMode

        thread {
            try {
                if (mode == "tailscale") {
                    tailscaleController.ensureStarted()
                    tailscaleController.setTargetEndpoint(endpoint)
                    val st = tailscaleController.getStatus()
                    if (st.state != "Running") {
                        runOnUiThread {
                            if (fallbackToLogin) showLoginGate()
                            webView.evaluateJavascript(
                                "window.onConnectResult && window.onConnectResult(false, 'Tailscale 尚未连接，请先完成授权或重连');",
                                null
                            )
                        }
                        return@thread
                    }
                }

                // 1. Check /health first
                val healthConn = tailscaleController.openMikuchinConnection(mode, endpoint, "/health", key)
                val healthCode = healthConn.responseCode
                healthConn.disconnect()
                if (healthCode !in 200..299) {
                    val msg = "无法访问服务健康检查 (HTTP $healthCode)"
                    runOnUiThread {
                        if (fallbackToLogin) showLoginGate()
                        webView.evaluateJavascript("window.onConnectResult && window.onConnectResult(false, ${JSONObject.quote(msg)});", null)
                    }
                    return@thread
                }

                // 2. Verify API Key and fetch recent sessions via /v1/strata/sessions
                val conn = tailscaleController.openMikuchinConnection(mode, endpoint, "/v1/strata/sessions", key)
                val code = conn.responseCode
                val body = if (code in 200..299) {
                    conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
                } else ""
                conn.disconnect()

                if (code in 200..299) {
                    var latestSessionId = ""
                    try {
                        val json = JSONObject(body)
                        val arr = json.optJSONArray("sessions")
                        var maxUpdated = -1.0
                        if (arr != null) {
                            for (i in 0 until arr.length()) {
                                val item = arr.optJSONObject(i) ?: continue
                                val updated = item.optDouble("updated", 0.0)
                                if (updated > maxUpdated) {
                                    maxUpdated = updated
                                    latestSessionId = item.optString("id", "")
                                }
                            }
                        }
                    } catch (_: Exception) {}

                    secureStore.activeEndpoint = endpoint
                    secureStore.apiKey = key
                    secureStore.latestSessionId = latestSessionId
                    secureStore.isConnected = true

                    val entryUrl = tailscaleController.buildWebViewEntryUrl(mode, endpoint)
                    runOnUiThread {
                        webView.loadUrl(entryUrl)
                    }
                } else {
                    val msg = if (code == 401) "key 错误或未填写" else "连接失败 (HTTP $code)"
                    runOnUiThread {
                        if (fallbackToLogin) showLoginGate()
                        webView.evaluateJavascript("window.onConnectResult && window.onConnectResult(false, ${JSONObject.quote(msg)});", null)
                    }
                }
            } catch (_: Exception) {
                val errHint = if (mode == "tailscale") {
                    "无法通过 Tailnet 连接到目标接口，请检查节点 ACL 授权与服务端状态"
                } else {
                    "无法连接到接口，请检查地址与网络"
                }
                runOnUiThread {
                    if (fallbackToLogin) showLoginGate()
                    webView.evaluateJavascript("window.onConnectResult && window.onConnectResult(false, ${JSONObject.quote(errHint)});", null)
                }
            }
        }
    }

    inner class AndroidBridge {
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
            val statusJson = tailscaleController.startInteractiveLogin().toJsonString()
            // Poll briefly in background so when AuthURL arrives we open it or update UI
            thread {
                var opened = false
                for (i in 0 until 25) {
                    Thread.sleep(500)
                    val st = tailscaleController.getStatus()
                    val pubJson = st.toJsonString()
                    runOnUiThread {
                        webView.evaluateJavascript("window.onTailscaleStatus && window.onTailscaleStatus(${JSONObject.quote(pubJson)});", null)
                    }
                    if (!opened && st.authUrl.startsWith("https://login.tailscale.com/")) {
                        opened = true
                        openAuthUrl(st.authUrl)
                    }
                    if (st.state == "Running") break
                }
            }
            return statusJson
        }

        @JavascriptInterface
        fun openAuthUrl(url: String) {
            if (!isCallerAuthorized()) return
            val trimmed = url.trim()
            if (!trimmed.startsWith("https://login.tailscale.com/")) return
            runOnUiThread {
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(trimmed)))
                } catch (_: Exception) {}
            }
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
            secureStore.isConnected = false
            showLoginGate()
        }
    }
}
