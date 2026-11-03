package com.mikuchin.client

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import org.json.JSONObject
import tsnetbridge.Tsnetbridge
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

data class TailscaleStatus(
    val state: String = "Stopped",
    val authUrl: String = "",
    val tailscaleIp: String = "",
    val hostname: String = "mikuchin-android",
    val socksPort: Int = 0,
    val httpProxyPort: Int = 0,
    val proxyToken: String = "",
    val target: String = "",
    val error: String = ""
) {
    fun toJsonString(): String {
        return JSONObject().apply {
            put("state", state)
            put("authUrl", authUrl)
            put("tailscaleIp", tailscaleIp)
            put("hostname", hostname)
            put("socksPort", socksPort)
            put("httpProxyPort", httpProxyPort)
            put("target", target)
            put("error", error)
        }.toString()
    }
}

/**
 * Manages the embedded user-space Tailscale (tsnet) node and local proxy without Android VpnService.
 */
class TailscaleController(private val context: Context) {

    companion object {
        const val DEFAULT_HOSTNAME = "mikuchin-android"
    }

    private val stateRootDir: File by lazy {
        File(context.noBackupFilesDir, "tailscale").apply { mkdirs() }
    }

    private var seqInitialized = false
    private var networkCallbackRegistered = false
    private var seenInitialNetwork = false
    private val connectivityManager by lazy {
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    }

    @Synchronized
    private fun ensureSeqContext() {
        if (seqInitialized) return
        go.Seq.setContext(context.applicationContext)
        seqInitialized = true
    }

    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            if (!seenInitialNetwork) {
                seenInitialNetwork = true
                return
            }
            try {
                ensureSeqContext()
                val st = getStatus()
                if (st.state == "Running" || st.state == "NeedsLogin") {
                    Tsnetbridge.reconnect()
                }
            } catch (_: Throwable) {}
        }
    }

    @Synchronized
    fun ensureStarted(): TailscaleStatus {
        return try {
            ensureSeqContext()
            Tsnetbridge.start(stateRootDir.absolutePath, DEFAULT_HOSTNAME)
            registerNetworkCallbackIfNeeded()
            getStatus()
        } catch (t: Throwable) {
            TailscaleStatus(state = "Error", error = t.message ?: t.javaClass.simpleName)
        }
    }

    fun startInteractiveLogin(): TailscaleStatus {
        val started = ensureStarted()
        if (started.state == "Error" && started.error.isNotEmpty()) {
            return started
        }
        return try {
            val raw = Tsnetbridge.startLogin()
            parseStatus(raw)
        } catch (t: Throwable) {
            TailscaleStatus(state = "Error", error = t.message ?: t.javaClass.simpleName)
        }
    }

    fun setTargetEndpoint(endpoint: String): Boolean {
        return try {
            ensureSeqContext()
            Tsnetbridge.setTarget(endpoint)
            true
        } catch (_: Throwable) {
            false
        }
    }

    fun getStatus(): TailscaleStatus {
        return try {
            ensureSeqContext()
            parseStatus(Tsnetbridge.getStatusJSON())
        } catch (t: Throwable) {
            TailscaleStatus(state = "Error", error = t.message ?: t.javaClass.simpleName)
        }
    }

    fun reconnect(): TailscaleStatus {
        return try {
            ensureSeqContext()
            Tsnetbridge.reconnect()
            getStatus()
        } catch (t: Throwable) {
            TailscaleStatus(state = "Error", error = t.message ?: t.javaClass.simpleName)
        }
    }

    fun logout(): TailscaleStatus {
        return try {
            ensureSeqContext()
            Tsnetbridge.logout()
            getStatus()
        } catch (t: Throwable) {
            TailscaleStatus(state = "Error", error = t.message ?: t.javaClass.simpleName)
        }
    }

    fun stop() {
        try {
            if (seqInitialized) {
                Tsnetbridge.stop()
            }
        } catch (_: Throwable) {}
    }

    /**
     * Opens an authenticated HttpURLConnection to a Mikuchin path (e.g. "/v1/strata/sessions" or "/health")
     * through the local tsnet HTTP reverse proxy when in Tailscale mode, or directly when in Direct mode.
     */
    fun openMikuchinConnection(mode: String, rawEndpoint: String, path: String, apiKey: String): HttpURLConnection {
        val cleanPath = if (path.startsWith("/")) path else "/$path"
        if (mode == "tailscale") {
            val st = ensureStarted()
            if (st.state != "Running" || st.httpProxyPort <= 0) {
                throw IllegalStateException("Tailscale 尚未连接就绪")
            }
            Tsnetbridge.setTarget(rawEndpoint)
            val proxyUrl = URL("http://127.0.0.1:${st.httpProxyPort}$cleanPath")
            return (proxyUrl.openConnection() as HttpURLConnection).apply {
                connectTimeout = 8000
                readTimeout = 8000
                setRequestProperty("X-Mikuchin-Proxy-Token", st.proxyToken)
                if (apiKey.isNotEmpty()) {
                    setRequestProperty("Authorization", "Bearer $apiKey")
                }
            }
        } else {
            var base = rawEndpoint.trim()
            if (!base.startsWith("http://", ignoreCase = true) && !base.startsWith("https://", ignoreCase = true)) {
                base = "http://$base"
            }
            base = base.trimEnd('/')
            val url = URL("$base$cleanPath")
            return (url.openConnection() as HttpURLConnection).apply {
                connectTimeout = 6000
                readTimeout = 6000
                if (apiKey.isNotEmpty()) {
                    setRequestProperty("Authorization", "Bearer $apiKey")
                }
            }
        }
    }

    /**
     * Returns the URL that the WebView should load once verified.
     * In Tailscale mode, loads the local reverse proxy entry URL which sets the HttpOnly session cookie
     * and redirects to "/", keeping all WebView requests (HTML, JS, SSE, uploads) same-origin and inside Tailnet.
     */
    fun buildWebViewEntryUrl(mode: String, rawEndpoint: String): String {
        if (mode == "tailscale") {
            val st = getStatus()
            Tsnetbridge.setTarget(rawEndpoint)
            return "http://127.0.0.1:${st.httpProxyPort}/__mk_entry?token=${st.proxyToken}"
        }
        var base = rawEndpoint.trim()
        if (!base.startsWith("http://", ignoreCase = true) && !base.startsWith("https://", ignoreCase = true)) {
            base = "http://$base"
        }
        return base.trimEnd('/')
    }

    /**
     * Returns the active origin ("scheme://host:port") currently authorized to access MikuchinAndroid JS bridge.
     */
    fun getAuthorizedWebOrigin(mode: String, rawEndpoint: String): String {
        if (mode == "tailscale") {
            val st = getStatus()
            if (st.httpProxyPort > 0) {
                return "http://127.0.0.1:${st.httpProxyPort}"
            }
            return ""
        }
        var base = rawEndpoint.trim()
        if (base.isEmpty()) return ""
        if (!base.startsWith("http://", ignoreCase = true) && !base.startsWith("https://", ignoreCase = true)) {
            base = "http://$base"
        }
        return try {
            val u = URL(base)
            val portPart = if (u.port != -1 && u.port != u.defaultPort) ":${u.port}" else ""
            "${u.protocol.lowercase()}://${u.host.lowercase()}$portPart"
        } catch (_: Exception) {
            ""
        }
    }

    private fun parseStatus(raw: String): TailscaleStatus {
        return try {
            val j = JSONObject(raw)
            TailscaleStatus(
                state = j.optString("state", "Stopped"),
                authUrl = j.optString("authUrl", ""),
                tailscaleIp = j.optString("tailscaleIp", ""),
                hostname = j.optString("hostname", DEFAULT_HOSTNAME),
                socksPort = j.optInt("socksPort", 0),
                httpProxyPort = j.optInt("httpProxyPort", 0),
                proxyToken = j.optString("proxyToken", ""),
                target = j.optString("target", ""),
                error = j.optString("error", "")
            )
        } catch (e: Exception) {
            TailscaleStatus(state = "Error", error = e.message ?: "invalid status JSON")
        }
    }

    private fun registerNetworkCallbackIfNeeded() {
        if (networkCallbackRegistered) return
        try {
            val req = NetworkRequest.Builder()
                .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .build()
            connectivityManager.registerNetworkCallback(req, networkCallback)
            networkCallbackRegistered = true
        } catch (_: Exception) {}
    }
}

