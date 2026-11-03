package com.mikuchin.client

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Hardware-backed Android Keystore encryption for sensitive credentials (Mikuchin API Key).
 * Never writes secrets to plaintext SharedPreferences or logs.
 */
class SecureStore(context: Context) {

    companion object {
        private const val KEYSTORE_PROVIDER = "AndroidKeyStore"
        private const val KEY_ALIAS = "mikuchin_keystore_aes_v1"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val GCM_TAG_BITS = 128
        private const val PREFS_NAME = "mikuchin_secure_prefs"
    }

    private val prefs: SharedPreferences =
        context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private fun getOrCreateSecretKey(): SecretKey {
        val keyStore = KeyStore.getInstance(KEYSTORE_PROVIDER).apply { load(null) }
        val existing = keyStore.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry
        if (existing != null) return existing.secretKey

        val keyGenerator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE_PROVIDER)
        val spec = KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build()
        keyGenerator.init(spec)
        return keyGenerator.generateKey()
    }

    private fun encrypt(plainText: String): String {
        if (plainText.isEmpty()) return ""
        return try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, getOrCreateSecretKey())
            val iv = cipher.iv
            val cipherBytes = cipher.doFinal(plainText.toByteArray(Charsets.UTF_8))
            val combined = ByteArray(1 + iv.size + cipherBytes.size)
            combined[0] = iv.size.toByte()
            System.arraycopy(iv, 0, combined, 1, iv.size)
            System.arraycopy(cipherBytes, 0, combined, 1 + iv.size, cipherBytes.size)
            Base64.encodeToString(combined, Base64.NO_WRAP)
        } catch (e: Exception) {
            ""
        }
    }

    private fun decrypt(encoded: String): String {
        if (encoded.isEmpty()) return ""
        return try {
            val combined = Base64.decode(encoded, Base64.NO_WRAP)
            if (combined.size < 2) return ""
            val ivLen = combined[0].toInt() and 0xFF
            if (combined.size < 1 + ivLen) return ""
            val iv = combined.copyOfRange(1, 1 + ivLen)
            val cipherBytes = combined.copyOfRange(1 + ivLen, combined.size)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, getOrCreateSecretKey(), GCMParameterSpec(GCM_TAG_BITS, iv))
            String(cipher.doFinal(cipherBytes), Charsets.UTF_8)
        } catch (e: Exception) {
            ""
        }
    }

    var connectionMode: String
        get() = prefs.getString("conn_mode", "direct") ?: "direct"
        set(value) = prefs.edit().putString("conn_mode", if (value == "tailscale") "tailscale" else "direct").apply()

    var directEndpoint: String
        get() = prefs.getString("direct_endpoint", "") ?: ""
        set(value) = prefs.edit().putString("direct_endpoint", value.trim()).apply()

    var tailscaleEndpoint: String
        get() = prefs.getString("ts_endpoint", "") ?: ""
        set(value) = prefs.edit().putString("ts_endpoint", value.trim()).apply()

    var activeEndpoint: String
        get() = if (connectionMode == "tailscale") tailscaleEndpoint else directEndpoint
        set(value) {
            if (connectionMode == "tailscale") tailscaleEndpoint = value else directEndpoint = value
        }

    var apiKey: String
        get() = decrypt(prefs.getString("apikey_enc", "") ?: "")
        set(value) = prefs.edit().putString("apikey_enc", encrypt(value.trim())).apply()

    var isConnected: Boolean
        get() = prefs.getBoolean("connected", false)
        set(value) = prefs.edit().putBoolean("connected", value).apply()

    var latestSessionId: String
        get() = prefs.getString("latest_session_id", "") ?: ""
        set(value) = prefs.edit().putString("latest_session_id", value).apply()
}

