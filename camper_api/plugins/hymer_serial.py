import asyncio
import logging
import struct
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

import serial

from ..config import settings
from ..database import get_db
from .. import crud, schemas

logger = logging.getLogger("uvicorn.camper-api.hymer_serial")


SOF = 0xAA
MAX_PAYLOAD = 56

OP_GET_HOUSEHOLD = 0x10
OP_GET_PUMP = 0x11
OP_GET_VOLTAGE = 0x12
OP_GET_WATER = 0x13
OP_GET_WASTE = 0x14
OP_GET_ALL = 0x15
OP_SET_HOUSEHOLD = 0x20
OP_SET_PUMP = 0x21
OP_SET_NEOPIXEL = 0x22
OP_SUBSCRIBE = 0x30
OP_UNSUBSCRIBE = 0x32
OP_ENTER_BOOTLOADER = 0x40
OP_PING = 0x41
OP_VERSION = 0x42
OP_GET_ERRORS = 0x43
OP_CLEAR_ERRORS = 0x44
OP_TELEMETRY_PUSH = 0x80
OP_EVENT = 0x81
OP_ACK = 0xF0
OP_NACK = 0xF1

NACK_REASONS = {
    0x01: "BAD_CRC",
    0x02: "BAD_LEN",
    0x03: "UNKNOWN_OPCODE",
    0x04: "BAD_PARAM",
    0x05: "BUSY",
}

ERROR_BITS = {
    0x0001: "HOUSEHOLD_SWITCH_FAILED",
    0x0002: "VOLTAGE_HOUSEHOLD_LOW",
    0x0004: "VOLTAGE_STARTER_LOW",
    0x0008: "VOLTAGE_MAINS_LOW",
    0x0010: "WATER_LOW",
    0x0020: "WASTE_HIGH",
    0x0040: "WASTE_FULL",
    0x0080: "ADC_STUCK",
    0x0100: "PROTOCOL_CRC",
    0x0200: "PROTOCOL_OVERRUN",
    0x0400: "BROWN_OUT",
}

NEOPIXEL_BLACK = 15


def crc16_mcrf4xx(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    return crc & 0xFFFF


def build_frame(opcode: int, payload: bytes = b"") -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload too long: {len(payload)}")
    body = bytes([opcode, len(payload)]) + payload
    crc = crc16_mcrf4xx(body)
    return bytes([SOF]) + body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def decode_errors_list(mask: int) -> list[str]:
    return [name for bit, name in ERROR_BITS.items() if mask & bit]


@dataclass
class Frame:
    opcode: int
    payload: bytes


class NackError(Exception):
    def __init__(self, opcode: int, reason: int):
        self.opcode = opcode
        self.reason = reason
        self.reason_name = NACK_REASONS.get(reason, f"0x{reason:02X}")
        super().__init__(f"NACK op=0x{opcode:02X} reason={self.reason_name}")


class FrameParser:
    """Stateful byte-by-byte parser; mirrors the firmware state machine."""

    IDLE, GOT_SOF, GOT_OP, IN_PAYLOAD, GOT_CRC_LO, GOT_CRC_HI = range(6)

    def __init__(self) -> None:
        self.state = self.IDLE
        self.opcode = 0
        self.length = 0
        self.payload = bytearray()
        self.crc_lo = 0

    def feed_stream(self, data: bytes) -> list[Frame]:
        out: list[Frame] = []
        for b in data:
            if self.state == self.IDLE:
                if b == SOF:
                    self.state = self.GOT_SOF
                    self.payload.clear()
                continue
            if self.state == self.GOT_SOF:
                self.opcode = b
                self.state = self.GOT_OP
                continue
            if self.state == self.GOT_OP:
                if b > MAX_PAYLOAD:
                    self.state = self.IDLE
                    continue
                self.length = b
                self.state = self.IN_PAYLOAD if b else self.GOT_CRC_LO
                continue
            if self.state == self.IN_PAYLOAD:
                self.payload.append(b)
                if len(self.payload) >= self.length:
                    self.state = self.GOT_CRC_LO
                continue
            if self.state == self.GOT_CRC_LO:
                self.crc_lo = b
                self.state = self.GOT_CRC_HI
                continue
            if self.state == self.GOT_CRC_HI:
                received = self.crc_lo | (b << 8)
                body = bytes([self.opcode, self.length]) + bytes(self.payload)
                if received == crc16_mcrf4xx(body):
                    out.append(Frame(self.opcode, bytes(self.payload)))
                self.state = self.IDLE
        return out


class HymerSerial:
    def __init__(self):
        self._serial = serial.Serial(
            settings.hymer_serial_port,
            settings.hymer_serial_speed,
            timeout=settings.hymer_serial_timeout,
        )

        self._db = next(get_db())

        self.sensor = crud.get_sensor_by_name(self._db, settings.hymer_sensor)
        if self.sensor is None:
            self.sensor = crud.create_sensor(
                self._db, schemas.SensorCreate(name=settings.hymer_sensor)
            )

        entities = crud.get_entities_by_sensor(self._db, self.sensor.id)
        self.entities_by_name = {e.name: e for e in entities}

        for entity_name in settings.hymer_entities:
            if entity_name not in self.entities_by_name.keys():
                entity = crud.create_entity(
                    self._db, schemas.EntityCreate(name=entity_name), self.sensor.id
                )
                self.entities_by_name[entity_name] = entity

        self.subscribe_until: datetime = datetime.min
        self._pending: dict[int, asyncio.Future] = {}
        self._parser = FrameParser()
        self._stop_evt = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tx_lock: asyncio.Lock | None = None
        self._reader_thread: threading.Thread | None = None
        self._keepalive_handle: asyncio.Task | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._tx_lock = asyncio.Lock()
        # Short read timeout so the reader thread checks _stop_evt promptly.
        self._serial.timeout = 1.0

        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="hymer-serial-reader", daemon=True
        )
        self._reader_thread.start()

        self._keepalive_handle = asyncio.create_task(self._keepalive_task())

        # Turn off both neopixels at startup (best-effort).
        for led in (1, 2):
            try:
                await self._request(
                    OP_SET_NEOPIXEL, bytes([led, NEOPIXEL_BLACK, 0])
                )
            except Exception as ex:
                logger.warning(f"neopixel{led} off failed: {ex!r}")

    async def stop(self) -> None:
        self._stop_evt.set()

        try:
            await self._request(OP_UNSUBSCRIBE, b"")
        except Exception:
            pass

        if self._keepalive_handle is not None:
            self._keepalive_handle.cancel()
            try:
                await self._keepalive_handle
            except (asyncio.CancelledError, Exception):
                pass

        try:
            self._serial.close()
        except Exception:
            pass

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=2.0)

    def bump_subscription(self, ttl_seconds: int = 30) -> None:
        self.subscribe_until = datetime.now() + timedelta(seconds=ttl_seconds)

    async def household(self, state) -> dict:
        s = int(state)
        frame = await self._request(OP_SET_HOUSEHOLD, bytes([s]))
        new_state = str(frame.payload[1])
        await self._store_state("household_state", new_state)
        return {"state": new_state}

    async def pump(self, state) -> dict:
        s = int(state)
        frame = await self._request(OP_SET_PUMP, bytes([s]))
        new_state = str(frame.payload[1])
        await self._store_state("pump_state", new_state)
        return {"state": new_state}

    async def errors(self, mask: str = "0xFFFF") -> dict:
        """Clear error bits matching `mask`, then store the remaining mask.

        Mirrors the shape of household() / pump(): takes a string from the
        /action body, returns a dict, updates the cached `errors` state.
        """
        mask_int = int(mask, 0)
        frame = await self._request(
            OP_CLEAR_ERRORS, struct.pack("<H", mask_int & 0xFFFF)
        )
        remaining = frame.payload[1] | (frame.payload[2] << 8)
        remaining_str = f"0x{remaining:04X}"
        await self._store_state("errors", remaining_str)
        return {"state": remaining_str, "bits": decode_errors_list(remaining)}

    # ---- internals ----

    def _reader_loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                data = self._serial.read(64)
            except Exception as ex:
                if self._stop_evt.is_set():
                    return
                logger.error(f"serial read error: {ex}")
                continue
            if not data:
                continue
            try:
                frames = self._parser.feed_stream(data)
            except Exception as ex:
                logger.error(f"parser error: {ex}")
                continue
            for frame in frames:
                # Bridge into the event loop. Bind frame in default arg to dodge
                # the late-binding closure trap in this for-loop.
                self._loop.call_soon_threadsafe(
                    lambda fr=frame: asyncio.create_task(self._on_frame(fr))
                )

    async def _on_frame(self, frame: Frame) -> None:
        op = frame.opcode
        if op == OP_TELEMETRY_PUSH:
            await self._handle_telemetry(frame.payload)
            return
        if op == OP_EVENT:
            self._handle_event(frame.payload)
            return
        if op == OP_ACK:
            if not frame.payload:
                logger.warning("ACK with empty payload")
                return
            acked = frame.payload[0]
            fut = self._pending.pop(acked, None)
            if fut is not None and not fut.done():
                fut.set_result(frame)
            else:
                logger.info(f"unmatched ACK op=0x{acked:02X}")
            return
        if op == OP_NACK:
            if len(frame.payload) < 2:
                logger.warning("NACK with short payload")
                return
            acked = frame.payload[0]
            reason = frame.payload[1]
            if acked == 0xFF:
                logger.warning(
                    f"unsolicited NACK reason={NACK_REASONS.get(reason, hex(reason))}"
                )
                return
            fut = self._pending.pop(acked, None)
            if fut is not None and not fut.done():
                fut.set_exception(NackError(acked, reason))
            else:
                logger.info(
                    f"unmatched NACK op=0x{acked:02X} "
                    f"reason={NACK_REASONS.get(reason, hex(reason))}"
                )
            return
        logger.info(f"unhandled frame op=0x{op:02X} payload={frame.payload.hex()}")

    async def _handle_telemetry(self, payload: bytes) -> None:
        if len(payload) != 11:
            logger.warning(f"bad telemetry length {len(payload)}")
            return
        vh, vm, vs, water, waste, flags, errs = struct.unpack("<HHHBBBH", payload)
        household_on = (flags >> 0) & 1
        pump_on = (flags >> 2) & 1
        # Firmware reports voltages in mV; convert to V for storage so the
        # database units match what the old ASCII protocol delivered.
        await self._store_state("household_voltage", f"{vh / 1000:.3f}")
        await self._store_state("mains_voltage", f"{vm / 1000:.3f}")
        await self._store_state("starter_voltage", f"{vs / 1000:.3f}")
        await self._store_state("water_state", str(water))
        await self._store_state("waste_state", str(waste))
        await self._store_state("household_state", str(household_on))
        await self._store_state("pump_state", str(pump_on))
        await self._store_state("errors", f"0x{errs:04X}")

    def _handle_event(self, payload: bytes) -> None:
        if len(payload) >= 3 and payload[0] == 0x01:
            mask = payload[1] | (payload[2] << 8)
            bits = decode_errors_list(mask)
            logger.warning(f"ERROR_RAISED mask=0x{mask:04X} bits={bits}")
            return
        kind = payload[:1].hex() if payload else ""
        logger.info(f"event kind={kind} body={payload[1:].hex()}")

    async def _request(
        self, opcode: int, payload: bytes = b"", timeout: float | None = None
    ) -> Frame:
        if self._tx_lock is None or self._loop is None:
            raise RuntimeError("HymerSerial.start() has not been called")
        if timeout is None:
            timeout = settings.hymer_request_timeout

        async with self._tx_lock:
            if opcode in self._pending:
                raise RuntimeError(
                    f"request for opcode 0x{opcode:02X} already in flight"
                )
            fut: asyncio.Future = self._loop.create_future()
            self._pending[opcode] = fut

            try:
                self._serial.write(build_frame(opcode, payload))
                self._serial.flush()
            except Exception:
                self._pending.pop(opcode, None)
                raise

        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(opcode, None)
            raise

    async def _keepalive_task(self) -> None:
        while not self._stop_evt.is_set():
            try:
                await asyncio.sleep(3)
            except asyncio.CancelledError:
                return
            if datetime.now() < self.subscribe_until:
                try:
                    await self._request(OP_SUBSCRIBE, bytes([0]))
                except (asyncio.TimeoutError, NackError, RuntimeError) as ex:
                    logger.warning(f"subscribe keepalive failed: {ex!r}")

    async def _store_state(self, entity_name, state):
        await crud.create_state(self._db, self.entities_by_name[entity_name].id, state)


def _self_check_crc() -> None:
    vectors = [
        (bytes.fromhex("41 04 DE AD BE EF"), 0x3A8F),
        (bytes.fromhex("41 04 50 49 4E 47"), 0x8629),
        (bytes.fromhex("21 01 01"), 0x6885),
        (bytes.fromhex("30 01 00"), 0xA645),
        (bytes.fromhex("40 01 5A"), 0xDB42),
    ]
    for data, expect in vectors:
        got = crc16_mcrf4xx(data)
        assert got == expect, f"CRC mismatch: {data.hex()} -> 0x{got:04X} != 0x{expect:04X}"


if __name__ == "__main__":
    _self_check_crc()
    print("CRC vectors OK")

    async def _smoke():
        h = HymerSerial()
        await h.start()
        try:
            frame = await h._request(OP_PING, b"PING")
            print("PING ACK:", frame.payload.hex())
        finally:
            await h.stop()

    asyncio.run(_smoke())
