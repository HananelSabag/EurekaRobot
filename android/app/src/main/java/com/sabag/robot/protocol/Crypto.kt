package com.sabag.robot.protocol

import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec

/** Byte and crypto helpers shared by the LAN and cloud protocols. */

fun md5(vararg parts: ByteArray): ByteArray = digest("MD5", parts)

fun sha256(vararg parts: ByteArray): ByteArray = digest("SHA-256", parts)

private fun digest(alg: String, parts: Array<out ByteArray>): ByteArray =
    MessageDigest.getInstance(alg).run { parts.forEach(::update); digest() }

fun ByteArray.hex(): String = joinToString("") { "%02x".format(it.toInt() and 0xFF) }

fun String.unhex(): ByteArray = chunked(2).map { it.toInt(16).toByte() }.toByteArray()

fun bytesOf(vararg values: Int): ByteArray = ByteArray(values.size) { values[it].toByte() }

infix fun ByteArray.xor(other: ByteArray): ByteArray = ByteArray(size) { (this[it].toInt() xor other[it].toInt()).toByte() }

fun ByteArray.u(index: Int): Int = if (index in indices) this[index].toInt() and 0xFF else 0

/** AES-ECB with PKCS#7 padding (Java calls it PKCS5 for 16-byte blocks). */
fun aesEcb(encrypt: Boolean, key: ByteArray, data: ByteArray): ByteArray =
    Cipher.getInstance("AES/ECB/PKCS5Padding").run {
        init(if (encrypt) Cipher.ENCRYPT_MODE else Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"))
        doFinal(data)
    }

/** AES-CBC; [pad] adds/removes PKCS#7 padding. */
fun aesCbc(encrypt: Boolean, key: ByteArray, iv: ByteArray, data: ByteArray, pad: Boolean): ByteArray =
    Cipher.getInstance(if (pad) "AES/CBC/PKCS5Padding" else "AES/CBC/NoPadding").run {
        init(if (encrypt) Cipher.ENCRYPT_MODE else Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), IvParameterSpec(iv))
        doFinal(data)
    }

fun hmacSha256Hex(key: String, message: String): String =
    Mac.getInstance("HmacSHA256").run {
        init(SecretKeySpec(key.toByteArray(Charsets.US_ASCII), "HmacSHA256"))
        doFinal(message.toByteArray(Charsets.US_ASCII)).hex()
    }
