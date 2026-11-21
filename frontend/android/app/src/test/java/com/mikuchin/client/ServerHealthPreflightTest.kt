package com.mikuchin.client

import org.junit.Assert.*
import org.junit.Test

class ServerHealthPreflightTest {
    private val native = """{"error":{"message":"Missing or invalid gateway API key","type":"unauthorized"}}"""

    @Test fun acceptsLegacyAndNativeHealth() {
        assertTrue(ServerHealthPreflight.accepts(200, null))
        assertTrue(ServerHealthPreflight.accepts(204, ""))
        assertTrue(ServerHealthPreflight.accepts(401, native))
    }

    @Test fun rejectsArbitraryUnauthorizedResponses() {
        assertFalse(ServerHealthPreflight.accepts(401, """{"error":{"message":"wrong upstream key","type":"unauthorized"}}"""))
        assertFalse(ServerHealthPreflight.accepts(401, """{"error":{"message":"Missing or invalid gateway API key","type":"wrong"}}"""))
        assertFalse(ServerHealthPreflight.accepts(401, "<html>Log in</html>"))
        assertFalse(ServerHealthPreflight.accepts(403, native))
        assertFalse(ServerHealthPreflight.accepts(404, null))
        assertFalse(ServerHealthPreflight.accepts(502, native))
        assertFalse(ServerHealthPreflight.accepts(401, native + " ".repeat(2050)))
    }
}
