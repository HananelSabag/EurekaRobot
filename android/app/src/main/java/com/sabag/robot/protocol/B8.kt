package com.sabag.robot.protocol

/**
 * 0xAA appliance frames for the robot (Midea device type B8, message protocol 1).
 * Port of midea-local's devices/b8/message.py, with what we verified on the NER 450:
 * the whole-home mode is ARC (0x02); it ignores AUTO (0x08).
 */
object B8 {
    private const val DEVICE_TYPE = 0xB8
    private const val PROTOCOL = 1
    private const val SET = 0x02
    private const val QUERY = 0x03
    private const val NOTIFY = 0x04

    enum class Mode(val code: Int) { ARC(0x02), EDGE(0x03), SCREW(0x05) }
    enum class Fan(val code: Int) { SOFT(0x01), NORMAL(0x02), HIGH(0x03) }
    enum class Water(val code: Int) { LOW(0x01), NORMAL(0x02), HIGH(0x03) }

    fun frame(messageType: Int, body: ByteArray): ByteArray {
        val data = bytesOf(0xAA, 10 + body.size, DEVICE_TYPE, 0, 0, 0, 0, 0, PROTOCOL, messageType) + body
        var sum = 0
        for (i in 1 until data.size) sum += data[i].toInt() and 0xFF
        return data + byteArrayOf(((sum.inv() + 1) and 0xFF).toByte())
    }

    fun query(): ByteArray = frame(QUERY, bytesOf(0x32, 0x01))

    /** Starts a clean; the robot only takes suction and water together with a start. */
    fun start(mode: Mode, fan: Fan, water: Water, volume: Int): ByteArray =
        frame(SET, bytesOf(0x22, 0x02, 0x02, mode.code, fan.code, water.code, volume.coerceIn(0, 100), 0) + ByteArray(7))

    fun stop(): ByteArray = frame(SET, bytesOf(0x22, 0x03, 0x00, 0x00))

    /** Return to dock. The robot treats it as a toggle: sent while already heading home, it stops. */
    fun dock(): ByteArray = frame(SET, bytesOf(0x22, 0x01, 0x00, 0x00))

    /** Parses a status frame (query reply or push notification); null for anything else. */
    fun parseStatus(frame: ByteArray): RobotStatus? {
        if (frame.size < 13 || frame.u(0) != 0xAA) return null
        val type = frame.u(9)
        val body = frame.copyOfRange(10, frame.size - 1)
        val offset = when {
            type == QUERY && body.u(0) == 0x32 && body.u(1) == 0x01 -> 1
            type == NOTIFY && body.u(0) == 0x42 -> 0
            else -> return null
        }
        fun b(i: Int) = body.u(i + offset)
        val statusByte = b(13)
        val errorType = ERROR_TYPES[b(14)] ?: "no"
        val errorDesc = when (errorType) {
            "can_fix" -> FIX_ERRORS[b(15)]
            "reboot" -> REBOOT_ERRORS[b(15)]
            "warning" -> WARNINGS[b(15)]
            else -> null
        } ?: "no"
        return RobotStatus(
            workStatus = WORK_STATUS[b(1)] ?: "none",
            controlType = CONTROL[b(3)] ?: "none",
            cleanMode = CLEAN_MODES[b(5)] ?: "none",
            fan = FANS[b(6)] ?: "off",
            area = b(7),
            water = WATERS[b(8)] ?: "off",
            voiceVolume = minOf(b(9), 100),
            battery = minOf(b(11), 100),
            workTime = b(12),
            deviceError = statusByte and 0x80 != 0,
            errorType = errorType,
            errorDesc = errorDesc,
            mop = MOP[b(16)] ?: "lack_water",
        )
    }

    private val WORK_STATUS = mapOf(
        0x00 to "none", 0x01 to "charge", 0x02 to "work", 0x03 to "stop", 0x04 to "charging_on_dock",
        0x05 to "reserve_task_finished", 0x06 to "charge_finish", 0x07 to "charging_with_wire", 0x08 to "pause",
        0x09 to "updating", 0x0A to "saving_map", 0x0B to "error", 0x0C to "sleep", 0x0D to "charge_pause",
        0x0E to "relocate", 0x0F to "electrolysed_water_making", 0x10 to "dust_collecting",
        0x11 to "back_dust_collecting", 0x12 to "sleep_in_station",
    )
    private val CONTROL = mapOf(0x0 to "none", 0x1 to "manual", 0x2 to "auto")
    private val CLEAN_MODES = mapOf(
        0x00 to "none", 0x01 to "random", 0x02 to "arc", 0x03 to "edge", 0x04 to "emphases", 0x05 to "screw",
        0x06 to "bed", 0x07 to "wide_screw", 0x08 to "auto", 0x09 to "area", 0x0A to "zone_index",
        0x0B to "zone_rect", 0x0C to "path",
    )
    private val FANS = mapOf(0x0 to "off", 0x1 to "soft", 0x2 to "normal", 0x3 to "high", 0x4 to "low")
    private val WATERS = mapOf(0x0 to "off", 0x1 to "low", 0x2 to "normal", 0x3 to "high")
    private val MOP = mapOf(0x0 to "off", 0x1 to "on", 0x2 to "lack_water")
    private val ERROR_TYPES = mapOf(0x00 to "no", 0x01 to "can_fix", 0x02 to "reboot", 0x03 to "warning")
    private val FIX_ERRORS = mapOf(
        0x00 to "no", 0x01 to "fix_dust", 0x02 to "fix_wheel_hang", 0x03 to "fix_wheel_overload",
        0x04 to "fix_side_brush_overload", 0x05 to "fix_roll_brush_overload", 0x06 to "fix_dust_engine",
        0x07 to "fix_front_panel", 0x08 to "fix_radar_mask", 0x09 to "fix_drop_sensor", 0x0A to "fix_low_battery",
        0x0B to "fix_abnormal_posture", 0x0C to "fix_laser_sensor", 0x0D to "fix_edge_sensor",
        0x0E to "fix_start_in_forbid_area", 0x0F to "fix_start_in_strong_magnetic", 0x10 to "fix_laser_sensor_blocked",
    )
    private val REBOOT_ERRORS = mapOf(
        0x00 to "no", 0x01 to "reboot_laser_comm_fail", 0x02 to "reboot_robot_comm_fail", 0x03 to "reboot_inner_fail",
    )
    private val WARNINGS = mapOf(
        0x00 to "no", 0x01 to "warn_location_fail", 0x02 to "warn_low_battery", 0x03 to "warn_full_dust",
        0x04 to "warn_low_water",
    )
}

data class RobotStatus(
    val workStatus: String,
    val controlType: String,
    val cleanMode: String,
    val fan: String,
    val area: Int,
    val water: String,
    val voiceVolume: Int,
    val battery: Int,
    val workTime: Int,
    val deviceError: Boolean,
    val errorType: String,
    val errorDesc: String,
    val mop: String,
)
