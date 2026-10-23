package com.sabag.robot.protocol

import java.security.SecureRandom

/**
 * Midea V3 ("8370") session framing and handshake. Port of midea-local's LocalSecurity:
 * the token is sent as the handshake, the reply proves the key, and the session key is
 * the reply's plaintext XOR our key. Every later message is AES-256-CBC with a SHA-256 tag.
 */
class V3Session(
    private val token: ByteArray,
    private val key: ByteArray,
    private val padding: (Int) -> ByteArray = { n -> ByteArray(n).also(SecureRandom()::nextBytes) },
) {
    private var tcpKey: ByteArray? = null
    private var requestCount = 0
    private val zeroIv = ByteArray(16)

    val ready: Boolean get() = tcpKey != null

    fun handshakeRequest(): ByteArray = encode(token, HANDSHAKE_REQUEST)

    /** [reply] is the 64 bytes after the 8-byte header of the robot's handshake answer. */
    fun completeHandshake(reply: ByteArray) {
        require(reply.size == 64) { "handshake reply must be 64 bytes, got ${reply.size}" }
        val plain = aesCbc(false, key, zeroIv, reply.copyOfRange(0, 32), pad = false)
        check(sha256(plain).contentEquals(reply.copyOfRange(32, 64))) { "robot rejected the key" }
        tcpKey = plain xor key
        requestCount = 0
    }

    fun encode(input: ByteArray, messageType: Int): ByteArray {
        var data = input
        var size = data.size
        var pad = 0
        val encrypted = messageType == ENCRYPTED_REQUEST || messageType == ENCRYPTED_RESPONSE
        if (encrypted && (size + 2) % 16 != 0) {
            pad = 16 - ((size + 2) and 0xF)
            size += pad + 32
            data += padding(pad)
        }
        val header = bytesOf(0x83, 0x70, size shr 8, size and 0xFF, 0x20, (pad shl 4) or messageType)
        data = bytesOf(requestCount shr 8, requestCount and 0xFF) + data
        requestCount = (requestCount + 1).let { if (it >= 0xFFFF) 0 else it }
        if (encrypted) {
            val sign = sha256(header, data)
            data = aesCbc(true, checkNotNull(tcpKey), zeroIv, data, pad = false) + sign
        }
        return header + data
    }

    /** Splits [buffer] into complete decoded messages and the incomplete remainder. */
    fun decode(buffer: ByteArray): Pair<List<ByteArray>, ByteArray> {
        val out = mutableListOf<ByteArray>()
        var rest = buffer
        while (rest.size >= 6) {
            check(rest.u(0) == 0x83 && rest.u(1) == 0x70) { "not an 8370 message" }
            val size = ((rest.u(2) shl 8) or rest.u(3)) + 8
            if (rest.size < size) break
            val header = rest.copyOfRange(0, 6)
            var data = rest.copyOfRange(6, size)
            rest = rest.copyOfRange(size, rest.size)
            val pad = header.u(5) shr 4
            val type = header.u(5) and 0xF
            if (type == ENCRYPTED_REQUEST || type == ENCRYPTED_RESPONSE) {
                val sign = data.copyOfRange(data.size - 32, data.size)
                data = aesCbc(false, checkNotNull(tcpKey), zeroIv, data.copyOfRange(0, data.size - 32), pad = false)
                check(sha256(header, data).contentEquals(sign)) { "message signature mismatch" }
                if (pad > 0) data = data.copyOf(data.size - pad)
            }
            out += data.copyOfRange(2, data.size)
        }
        return out to rest
    }

    companion object {
        const val HANDSHAKE_REQUEST = 0x0
        const val HANDSHAKE_RESPONSE = 0x1
        const val ENCRYPTED_RESPONSE = 0x3
        const val ENCRYPTED_REQUEST = 0x6
    }
}
