package com.sabag.robot.protocol

import java.time.ZoneOffset
import java.time.ZonedDateTime

/**
 * The 5A5A packet that carries an 0xAA frame, on the LAN (frame AES-encrypted) and through the
 * cloud pass-through (frame in the clear). Port of midea-local's packet_builder.py.
 */
object Packet {
    val SIGN_KEY: ByteArray = "xhdiwjnchekd4d512chdjx5d8e4c394D2D7S".toByteArray(Charsets.US_ASCII)
    val ENC_KEY: ByteArray = md5(SIGN_KEY)
    private const val HEADER_SIZE = 40

    /** [centiseconds, second, minute, hour, day, month, year % 100, year / 100] in UTC. */
    fun timeBytes(now: ZonedDateTime = ZonedDateTime.now(ZoneOffset.UTC)): ByteArray =
        bytesOf(now.nano / 10_000_000, now.second, now.minute, now.hour, now.dayOfMonth, now.monthValue,
            now.year % 100, now.year / 100)

    fun build(deviceId: Long, frame: ByteArray, time: ByteArray = timeBytes()): ByteArray =
        assemble(deviceId, aesEcb(true, ENC_KEY, frame), time)

    fun buildForCloud(deviceId: Long, frame: ByteArray, time: ByteArray = timeBytes()): ByteArray =
        assemble(deviceId, frame, time)

    private fun assemble(deviceId: Long, payload: ByteArray, time: ByteArray): ByteArray {
        val header = ByteArray(HEADER_SIZE)
        bytesOf(0x5A, 0x5A, 0x01, 0x11, 0x00, 0x00, 0x20, 0x00).copyInto(header)
        time.copyInto(header, 12)
        for (i in 0 until 8) header[20 + i] = (deviceId ushr (8 * i)).toByte()
        val packet = header + payload
        val length = packet.size + 16
        packet[4] = length.toByte()
        packet[5] = (length shr 8).toByte()
        return packet + md5(packet, SIGN_KEY)
    }

    /** The decrypted 0xAA frame inside a LAN 5A5A packet, or null if it carries none. */
    fun openLan(packet: ByteArray): ByteArray? {
        if (packet.size <= HEADER_SIZE + 16 || packet.u(0) != 0x5A || packet.u(1) != 0x5A) return null
        val encrypted = packet.copyOfRange(HEADER_SIZE, packet.size - 16)
        if (encrypted.size % 16 != 0) return null
        return runCatching { aesEcb(false, ENC_KEY, encrypted) }.getOrNull()
    }

    /** The 0xAA frame inside a cloud pass-through reply (sent in the clear, zero-padded signature). */
    fun openCloud(packet: ByteArray): ByteArray? {
        if (packet.size <= HEADER_SIZE + 16) return null
        val frame = packet.copyOfRange(HEADER_SIZE, packet.size - 16)
        return if (frame.u(0) == 0xAA && frame.u(1) + 1 <= frame.size) frame.copyOf(frame.u(1) + 1) else null
    }
}
