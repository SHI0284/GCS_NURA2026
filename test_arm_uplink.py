import time
import unittest
from unittest import mock

import app
import protocol as p
from uplink import DeployResult, PyroUplink


SAFE_FAST = (
    "rx type=FAST seq=40 boot_ms=12000 state=SAFE state_code=1 status=0x0181 "
    "baro_dp_2pa=0 accel_g=(0.00,0.00,1.00) gyro_dps=(0.0,0.0,0.0) "
    "batt_mv=12000 health=imu,baro,gps,radio rssi=-35 snr=9.5"
)


class ArmProtocolTest(unittest.TestCase):
    def test_arm_uses_reserved_control_fields_and_authenticates_them(self):
        frame_seq = 0x1234
        frame = p.build_arm_flight_frame(
            command_seq=0x3344,
            frame_seq=frame_seq,
            nonce=0xA1B2C3D4,
            valid_until_ms=54321,
        )

        self.assertEqual(len(frame), p.FRAME_OVERHEAD + p.CONTROL_PAYLOAD_LEN)
        parsed = p.decode_frame(frame, direction=p.FRAME_DIRECTION_UPLINK)
        self.assertIsNotNone(parsed)
        control = p.ControlPayload.decode(parsed.payload)
        self.assertEqual(control.subtype, p.CONTROL_CMD)
        self.assertEqual(control.command_id, p.COMMAND_ARM_FLIGHT)
        self.assertEqual(control.param0, p.FLIGHT_SAFE)
        self.assertEqual(control.param1, p.FLIGHT_ARMED)
        self.assertEqual(control.valid_until_ms, 54321)
        self.assertEqual(
            control.auth_or_ack,
            p.make_control_auth_tag(control, frame_seq),
        )

    def test_arm_frame_never_allows_non_expiring_deadline(self):
        with self.assertRaises(ValueError):
            p.build_arm_flight_frame(1, 2, 3, 0)

    def test_simulated_arm_reports_final_armed_state(self):
        result = PyroUplink(simulate=True).arm_flight(valid_until_ms=1000)

        self.assertTrue(result.success)
        self.assertEqual(result.stage, p.ACK_EXECUTED)
        self.assertEqual(result.flight_state, p.FLIGHT_ARMED)


class ArmAckValidationTest(unittest.TestCase):
    class FakeSerial:
        def __init__(self, chunk: bytes):
            self.chunk = chunk
            self.is_open = True
            self.writes = []

        def write(self, data: bytes) -> int:
            self.writes.append(data)
            return len(data)

        def flush(self) -> None:
            pass

        def read(self, _max_bytes: int) -> bytes:
            chunk, self.chunk = self.chunk, b""
            return chunk

        def close(self) -> None:
            self.is_open = False

    @staticmethod
    def _ack_frame(command_seq: int, nonce: int, flight_state: int,
                   stage: int = p.ACK_EXECUTED, frame_seq: int = 9) -> bytes:
        control = p.ControlPayload(
            subtype=p.CONTROL_ACK,
            command_id=p.COMMAND_ARM_FLIGHT,
            command_seq=command_seq,
            nonce=nonce,
            auth_or_ack=bytes((
                stage,
                p.RESULT_OK,
                p.REJECT_NONE,
                flight_state,
                0, 0, 0, 0,
            )),
        )
        return p.encode_frame(
            p.MESSAGE_CONTROL,
            frame_seq,
            control.encode(),
            direction=p.FRAME_DIRECTION_DOWNLINK,
        )

    def test_executed_ack_with_safe_state_fails_closed(self):
        command_seq = 7
        nonce = 0x10203040
        link = PyroUplink(port="fake", serial_mode="raw")
        link._ser = self.FakeSerial(
            self._ack_frame(command_seq, nonce, p.FLIGHT_SAFE)
        )

        result = link._send_command_frame_locked(
            b"arm-frame",
            command_seq,
            nonce,
            p.COMMAND_ARM_FLIGHT,
            0.2,
            "ARM ACK",
            expected_flight_state=p.FLIGHT_ARMED,
        )

        self.assertFalse(result.success)
        self.assertIn("expected=2, received=1", result.message)

    def test_duplicate_safe_ack_waits_for_original_executed_armed_ack(self):
        command_seq = 8
        nonce = 0x50607080
        ack_bytes = (
            self._ack_frame(
                command_seq,
                nonce,
                p.FLIGHT_SAFE,
                stage=p.ACK_DUPLICATE,
                frame_seq=10,
            )
            + self._ack_frame(
                command_seq,
                nonce,
                p.FLIGHT_ARMED,
                stage=p.ACK_EXECUTED,
                frame_seq=11,
            )
        )
        link = PyroUplink(port="fake", serial_mode="raw")
        link._ser = self.FakeSerial(ack_bytes)

        result = link._send_command_frame_locked(
            b"arm-frame",
            command_seq,
            nonce,
            p.COMMAND_ARM_FLIGHT,
            0.2,
            "ARM ACK",
            expected_flight_state=p.FLIGHT_ARMED,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.flight_state, p.FLIGHT_ARMED)


class ArmApiTest(unittest.TestCase):
    class FakeHardwareLink:
        simulate = False
        serial_mode = "raw"
        port = "/dev/fake-ground"

        def __init__(self):
            self.valid_until_ms = None

        def is_open(self) -> bool:
            return True

        def diagnostics(self) -> dict:
            return {"bridge_status": {"radio": "ready"}}

        def arm_flight(self, valid_until_ms: int) -> DeployResult:
            self.valid_until_ms = valid_until_ms
            result = DeployResult()
            result.success = True
            result.stage = p.ACK_EXECUTED
            result.result = p.RESULT_OK
            result.reason = p.REJECT_NONE
            result.flight_state = p.FLIGHT_ARMED
            result.command_seq = 17
            result.attempts = 1
            result.message = "ARM ACK"
            return result

    def setUp(self):
        self.original_uplink = app.uplink
        app.telemetry.reset()
        app.hardware_telemetry.reset()
        self.client = app.app.test_client()

    def tearDown(self):
        app.uplink = self.original_uplink
        app.telemetry.reset()
        app.hardware_telemetry.reset()

    def test_confirmation_token_and_expected_source_state_are_mandatory(self):
        app.uplink = PyroUplink(simulate=True)

        response = self.client.post("/api/flight/arm", json={"confirm": "ARM"})
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/api/flight/arm",
            json={"confirm": "arm", "expected_state": p.FLIGHT_SAFE},
        )
        self.assertEqual(response.status_code, 400)

    def test_simulation_arm_completes_only_with_armed_ack(self):
        app.uplink = PyroUplink(simulate=True)

        response = self.client.post(
            "/api/flight/arm",
            json={"confirm": "ARM", "expected_state": p.FLIGHT_SAFE},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["flight_state"], p.FLIGHT_ARMED)
        self.assertEqual(payload["command_id"], p.COMMAND_ARM_FLIGHT)
        status = self.client.get("/api/flight/arm/status").get_json()
        self.assertFalse(status["eligible"])
        self.assertEqual(status["state_code"], p.FLIGHT_ARMED)

    def test_fresh_authenticated_safe_state_allows_hardware_arm(self):
        link = self.FakeHardwareLink()
        app.uplink = link
        self.assertTrue(app.hardware_telemetry._apply_receiver_fast_line(SAFE_FAST))

        with mock.patch.object(app, "avionics_downlink_only", return_value=False), \
             mock.patch.object(p, "RADIO_IDENTITY_PROVISIONED", True):
            status_response = self.client.get("/api/flight/arm/status")
            arm_response = self.client.post(
                "/api/flight/arm",
                json={"confirm": "ARM", "expected_state": p.FLIGHT_SAFE},
            )

        self.assertEqual(status_response.status_code, 200)
        self.assertTrue(status_response.get_json()["eligible"])
        self.assertEqual(arm_response.status_code, 200)
        self.assertIsNotNone(link.valid_until_ms)
        self.assertNotEqual(link.valid_until_ms, 0)

    def test_stale_fast_state_blocks_arm_even_after_newer_gps_or_http_activity(self):
        app.uplink = self.FakeHardwareLink()
        self.assertTrue(app.hardware_telemetry._apply_receiver_fast_line(SAFE_FAST))
        with app.hardware_telemetry.lock:
            app.hardware_telemetry.last_fast_at = time.monotonic() - 2.0
            app.hardware_telemetry.last_packet_at = time.monotonic()

        with mock.patch.object(app, "avionics_downlink_only", return_value=False), \
             mock.patch.object(p, "RADIO_IDENTITY_PROVISIONED", True):
            response = self.client.post(
                "/api/flight/arm",
                json={"confirm": "ARM", "expected_state": p.FLIGHT_SAFE},
            )

        self.assertEqual(response.status_code, 409)
        blocker_codes = {
            item["code"] for item in response.get_json()["arm_status"]["blockers"]
        }
        self.assertIn("STALE_FAST_TELEMETRY", blocker_codes)

    def test_public_bench_identity_blocks_hardware_arm(self):
        app.uplink = self.FakeHardwareLink()
        self.assertTrue(app.hardware_telemetry._apply_receiver_fast_line(SAFE_FAST))

        with mock.patch.object(app, "avionics_downlink_only", return_value=False), \
             mock.patch.object(p, "RADIO_IDENTITY_PROVISIONED", False):
            response = self.client.get("/api/flight/arm/status")

        self.assertFalse(response.get_json()["eligible"])
        blocker_codes = {item["code"] for item in response.get_json()["blockers"]}
        self.assertIn("PUBLIC_BENCH_IDENTITY", blocker_codes)


if __name__ == "__main__":
    unittest.main()
