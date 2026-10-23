"""Generate byte-exact test vectors from the Python libraries that already work with the robot.

The Android app's Kotlin port must reproduce every value here. Randomness and clocks are pinned.
Run from the project folder:  .venv\\Scripts\\python -m tools.gen_vectors > android/app/src/test/resources/vectors.json
"""

import hashlib
import json
from unittest import mock

import midealocal.security as lsec
from midea_beautiful.cloud import _encode_as_csv
from midea_beautiful.crypto import Security
from midea_beautiful.midea import SUPPORTED_APPS
from midealocal.devices.b8 import MideaB8Device
from midealocal.devices.b8.message import (
    B8CleanMode, B8FanLevel, B8WaterLevel, B8WorkMode, MessageQuery, MessageSet, MessageSetCommand,
)
from midealocal.packet_builder import PacketBuilder

DEVICE_ID = 123456789012345
FIXED_TIME = bytearray([12, 34, 56, 11, 24, 10, 26, 20])
v: dict = {"device_id": DEVICE_ID, "packet_time": FIXED_TIME.hex()}

# ---- 0xAA appliance frames (message protocol version 1, as this robot reports) ----
start = MessageSet(1)
start.clean_mode, start.fan_level, start.water_level, start.voice_volume = (
    B8CleanMode.ARC, B8FanLevel.NORMAL, B8WaterLevel.LOW, 70)
v["frames"] = {
    "query": MessageQuery(1).serialize().hex(),
    "start_arc_normal_low_70": start.serialize().hex(),
    "stop": MessageSetCommand(1, B8WorkMode.STOP).serialize().hex(),
    "dock": MessageSetCommand(1, B8WorkMode.CHARGE).serialize().hex(),
}

# ---- 5A5A packet around a frame (local, AES-128-ECB inside, MD5 signature) ----
with mock.patch.object(PacketBuilder, "packet_time", staticmethod(lambda: bytearray(FIXED_TIME))):
    v["packet_5a5a_query"] = PacketBuilder(DEVICE_ID, bytes.fromhex(v["frames"]["query"])).finalize().hex()

# ---- V3 (8370) session ----
key_a = bytes(range(32))                 # what we send as "key" (A)
plain_b = bytes(range(100, 132))         # what the robot would pick (B)
loc = lsec.LocalSecurity()
handshake_reply = loc.aes_cbc_encrypt(plain_b, key_a) + hashlib.sha256(plain_b).digest()
tcp_key = loc.tcp_key(handshake_reply, key_a)
v["v3"] = {"key": key_a.hex(), "handshake_reply_64": handshake_reply.hex(), "tcp_key": tcp_key.hex()}
with mock.patch.object(lsec, "get_random_bytes", lambda n: bytes(n)):
    pkt = bytes.fromhex(v["packet_5a5a_query"])
    v["v3"]["encrypted_request"] = loc.encode_8370(pkt, lsec.MSGTYPE_ENCRYPTED_REQUEST).hex()
    v["v3"]["handshake_request"] = lsec.LocalSecurity().encode_8370(bytes(range(64)), lsec.MSGTYPE_HANDSHAKE_REQUEST).hex()
    resp_sec = lsec.LocalSecurity()
    resp_sec._tcp_key = tcp_key
    v["v3"]["encrypted_response"] = resp_sec.encode_8370(pkt, lsec.MSGTYPE_ENCRYPTED_RESPONSE).hex()
dec = lsec.LocalSecurity()
dec._tcp_key = tcp_key
v["v3"]["decoded_response"] = dec.decode_8370(bytes.fromhex(v["v3"]["encrypted_response"]))[0][0].hex()

# ---- B8 status parsing: real frames this robot sent on 2026-10-23 ----
dev = MideaB8Device(name="t", device_id=DEVICE_ID, ip_address="0.0.0.0", port=6444, token="00", key="00",
                    device_protocol=3, model="320VR900", subtype=0, customize="")
samples = {
    "query_charging_50": "aa1cb80000000000010332010401000002020001460032000000000190",
    "notify_work": "aa1bb80000000000010442020002000202000101003200000000010e",
}
v["status"] = {}
for name, frame_hex in samples.items():
    frame = bytes.fromhex(frame_hex)
    if name == "notify_work":  # rebuild with a correct checksum from the logged body
        body = bytes.fromhex("4202000200020200010100320000000001")
        header = bytes([0xAA, 10 + len(body), 0xB8, 0, 0, 0, 0, 0, 1, 0x04])
        data = header + body
        frame = data + bytes([(~sum(data[1:]) + 1) & 0xFF])
    status = dev.process_message(frame)
    v["status"][name] = {"frame": frame.hex(), "parsed": {k: (str(x) if not isinstance(x, (int, bool)) else x)
                                                          for k, x in status.items()}}

# ---- MSmartHome cloud (proxied v5) ----
app = SUPPORTED_APPS["MSmartHome"]
sec = Security(appkey=app["appkey"], signkey=app["signkey"], iotkey=app["iotkey"], hmackey=app["hmackey"])
login_id, password = "a1b2c3d4", "Test-Password-123"
body = json.dumps({"loginAccount": "user@example.com", "stamp": "20261024000000"})
digest = hashlib.sha256(app["appkey"].encode()).hexdigest()
enc_key, enc_iv = digest[:16], digest[16:32]
token_plain, random_plain = "0123456789abcdef", "fedcba9876543210"
access_token = sec.aes_encrypt_string(token_plain, enc_key, enc_iv)
random_data = sec.aes_encrypt_string(random_plain, enc_key, enc_iv)
sec.set_access_token(access_token, random_data)
csv = _encode_as_csv(bytes.fromhex(v["packet_5a5a_query"]))
v["cloud"] = {
    "appkey": app["appkey"], "iotkey": app["iotkey"], "hmackey": app["hmackey"],
    "sign_body": body, "sign_random": "1792800000",
    "sign": sec.sign_proxied(None, data=body, random="1792800000"),
    "login_id": login_id, "password": password,
    "encrypted_password": sec.encrypt_password(login_id, password),
    "encrypted_iam_password": sec.encrypt_iam_password(login_id, password),
    "access_token": access_token, "random_data": random_data,
    "data_key": sec.data_key, "data_iv": sec._data_iv,
    "csv": csv, "order": sec.aes_encrypt_string(csv),
    "device_id_for_account": lsec.CloudSecurity.get_deviceid("user@example.com"),
    "udpid": {str(m): lsec.CloudSecurity.get_udp_id(DEVICE_ID, m) for m in (0, 1, 2)},
}
print(json.dumps(v, indent=1))
