package com.mikuchin.client

import org.json.JSONObject

/**
 * An unauthenticated health preflight never sends a credential.
 *
 * The stable server returns 2xx while Native intentionally requires Bearer
 * for /health and sends its recognizable 401 JSON. Neither response proves
 * identity; the chosen endpoint still must pass an authorized sessions fetch.
 */
internal object ServerHealthPreflight {
    fun accepts(status: Int, body: String?): Boolean {
        if (status in 200..299) return true
        if (status != 401 || body.isNullOrBlank() || body.length > 2048) return false
        return try {
            val error = JSONObject(body).optJSONObject("error") ?: return false
            error.optString("type") == "unauthorized" &&
                error.optString("message") == "Missing or invalid gateway API key"
        } catch (_: Exception) {
            false
        }
    }
}
