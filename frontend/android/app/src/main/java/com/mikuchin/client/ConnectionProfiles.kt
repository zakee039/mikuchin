package com.mikuchin.client

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** Persisted user-approved server addresses; never discover servers by SSID. */
data class ConnectionProfile(
    val id: String,
    val name: String,
    val mode: String,
    val endpoint: String,
    val encryptedKey: String,
    val wifiSsid: String = ""
) {
    fun publicJson() = JSONObject().apply {
        put("id", id)
        put("name", name)
        put("mode", mode)
        put("endpoint", endpoint)
        put("wifiSsid", wifiSsid)
    }
}

class ConnectionProfiles(context: Context, private val secrets: SecureStore) {
    private val prefs = context.applicationContext.getSharedPreferences(
        "mikuchin_connection_profiles", Context.MODE_PRIVATE)

    init {
        // One-time migration: keep both formerly independent direct/Tailscale
        // addresses, selected mode, and encrypted API key from the old app.
        if (!prefs.contains("entries_v1")) {
            val oldKey = secrets.encryptProfileKey(secrets.apiKey)
            val entries = mutableListOf<ConnectionProfile>()
            if (secrets.directEndpoint.isNotBlank()) {
                entries += ConnectionProfile(UUID.randomUUID().toString(), "局域网直连", "direct",
                    secrets.directEndpoint, oldKey)
            }
            if (secrets.tailscaleEndpoint.isNotBlank()) {
                entries += ConnectionProfile(UUID.randomUUID().toString(), "Tailscale", "tailscale",
                    secrets.tailscaleEndpoint, oldKey)
            }
            save(entries)
            prefs.edit().putString("preferred_entry", entries.firstOrNull {
                it.mode == secrets.connectionMode
            }?.id ?: entries.firstOrNull()?.id.orEmpty()).apply()
        }
    }

    @Synchronized
    fun all(): List<ConnectionProfile> {
        val json = try {JSONArray(prefs.getString("entries_v1", "[]"))} catch (_: Exception) {JSONArray()}
        return buildList {
            for (i in 0 until json.length()) {
                val item = json.optJSONObject(i) ?: continue
                val id = item.optString("id").takeIf {it.matches(Regex("[A-Za-z0-9-]{1,64}"))} ?: continue
                val endpoint = item.optString("endpoint").trim()
                if (endpoint.isEmpty()) continue
                add(ConnectionProfile(id, item.optString("name", "入口").take(45),
                    if (item.optString("mode") == "tailscale") "tailscale" else "direct",
                    endpoint, item.optString("encryptedKey"), item.optString("wifiSsid")))
            }
        }
    }

    @Synchronized
    private fun save(entries: List<ConnectionProfile>) {
        val array = JSONArray()
        entries.forEach {p ->
            array.put(p.publicJson().apply {put("encryptedKey", p.encryptedKey)})
        }
        prefs.edit().putString("entries_v1", array.toString()).apply()
    }

    fun keyOf(profile: ConnectionProfile) = secrets.decryptProfileKey(profile.encryptedKey)

    @Synchronized
    fun byId(id: String): ConnectionProfile? = all().firstOrNull {it.id == id}

    @Synchronized
    fun upsert(id: String?, name: String, mode: String, endpoint: String, key: String): ConnectionProfile {
        val normalizedName = name.trim().take(45)
        require(normalizedName.isNotEmpty()) {"请输入入口名称"}
        require(mode in listOf("direct", "tailscale")) {"不支持的连接类型"}
        require(endpoint.trim().length in 3..300) {"请输入有效接口地址"}
        // No invisible failover targets: every entry must be user supplied.
        val list = all().toMutableList()
        require(list.size < 24 || list.any {it.id == id}) {"最多保存 24 个入口"}
        val previous = list.firstOrNull {it.id == id}
        val profile = ConnectionProfile(previous?.id ?: UUID.randomUUID().toString(),
            normalizedName, mode, endpoint.trim(), secrets.encryptProfileKey(key.trim()),
            previous?.wifiSsid.orEmpty())
        list.removeAll {it.id == profile.id}
        list.add(profile)
        save(list)
        return profile
    }

    @Synchronized
    fun delete(id: String) {
        save(all().filterNot {it.id == id})
        if (preferredId == id) preferredId = ""
    }

    @Synchronized
    fun bindWifi(id: String, ssid: String): Boolean {
        if (ssid.isBlank() || ssid.length > 128) return false
        val list = all().toMutableList()
        val index = list.indexOfFirst {it.id == id}
        if (index < 0) return false
        // One preferred entry per SSID, preventing contradictory remembered rules.
        for (i in list.indices) if (list[i].wifiSsid == ssid) list[i] = list[i].copy(wifiSsid = "")
        list[index] = list[index].copy(wifiSsid = ssid)
        save(list)
        return true
    }

    @Synchronized
    fun clearWifi(id: String) {
        val list = all().map {if (it.id == id) it.copy(wifiSsid = "") else it}
        save(list)
    }

    var preferredId: String
        get() = prefs.getString("preferred_entry", "") ?: ""
        set(value) = prefs.edit().putString("preferred_entry", value).apply()

    var autoEnabled: Boolean
        get() = prefs.getBoolean("auto_connect", true)
        set(value) = prefs.edit().putBoolean("auto_connect", value).apply()

    fun snapshot(ssid: String?): String = JSONObject().apply {
        val list = all()
        put("entries", JSONArray().also {array -> list.forEach {array.put(it.publicJson())}})
        put("preferredId", preferredId)
        put("autoEnabled", autoEnabled)
        put("currentSsid", ssid.orEmpty())
        put("ssidAvailable", !ssid.isNullOrBlank())
    }.toString()

    fun candidates(ssid: String?): List<ConnectionProfile> {
        val entries = all()
        val remembered = ssid?.let {wifi -> entries.firstOrNull {it.wifiSsid == wifi}}
        val preferred = entries.firstOrNull {it.id == preferredId}
        // Untrusted/unknown Wi-Fi must NEVER trigger an automatic plaintext
        // LAN attempt: the same private IP can belong to an attacker on a
        // different network. User may still tap such an entry manually.
        // SSID binding is an explicit opt-in convenience, not server identity.
        val secure = {p: ConnectionProfile ->
            p.mode == "tailscale" || p.endpoint.startsWith("https://", ignoreCase = true)
        }
        val trustedLocal = remembered?.takeIf {it.wifiSsid.isNotEmpty()}
        return (listOfNotNull(trustedLocal, preferred?.takeIf(secure)) +
            entries.filter(secure)).distinctBy {it.id}
    }
}
