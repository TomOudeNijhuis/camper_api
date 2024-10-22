import asyncio
from typing import Set, Any
from datetime import datetime, timezone
import struct
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from .bthome_const import MEAS_TYPES

import time
import logging


logger = logging.getLogger(__name__)


def short_address(address: str) -> str:
    """Convert a Bluetooth address to a short address."""
    results = address.replace("-", ":").split(":")
    last: str = results[-1]
    second_last: str = results[-2]
    return f"{second_last.upper()}{last.upper()}"[-4:]


def to_mac(addr: bytes) -> str:
    """Return formatted MAC address."""
    return ":".join(f"{i:02X}" for i in addr)


def parse_uint(data_obj: bytes, factor: float = 1.0) -> float:
    """Convert bytes (as unsigned integer) and factor to float."""
    decimal_places = -int(f"{factor:e}".split("e")[-1])
    return round(
        int.from_bytes(data_obj, "little", signed=False) * factor, decimal_places
    )


def parse_int(data_obj: bytes, factor: float = 1.0) -> float:
    """Convert bytes (as signed integer) and factor to float."""
    decimal_places = -int(f"{factor:e}".split("e")[-1])
    return round(
        int.from_bytes(data_obj, "little", signed=True) * factor, decimal_places
    )


def parse_float(data_obj: bytes, factor: float = 1.0) -> float | None:
    """Convert bytes (as float) and factor to float."""
    decimal_places = -int(f"{factor:e}".split("e")[-1])
    if len(data_obj) == 2:
        [val] = struct.unpack("e", data_obj)
    elif len(data_obj) == 4:
        [val] = struct.unpack("f", data_obj)
    elif len(data_obj) == 8:
        [val] = struct.unpack("d", data_obj)
    else:
        logger.error("only 2, 4 or 8 byte long floats are supported in BTHome BLE")
        return None
    return round(val * factor, decimal_places)


def parse_raw(data_obj: bytes) -> str | None:
    """Convert bytes to raw hex string."""
    return data_obj.hex()


def parse_string(data_obj: bytes) -> str | None:
    """Convert bytes to string."""
    try:
        return data_obj.decode("UTF-8")
    except UnicodeDecodeError:
        logger.error(
            "BTHome data contains bytes that can't be decoded to a string (use UTF-8 encoding)"
        )
        return None


def parse_timestamp(data_obj: bytes) -> datetime:
    """Convert bytes to a datetime object."""
    value = datetime.fromtimestamp(
        int.from_bytes(data_obj, "little", signed=False), tz=timezone.utc
    )
    return value


class BTHomeBaseScanner:
    def __init__(self, addresses: list[str], callback=None):
        self.addresses = [a.lower() for a in addresses]
        self.last_packet_id = None
        self.last_adv_time = None
        self.last_packet_id = None
        self.mac_readable = None
        self.sleepy_device = None
        self.callback = callback

    def _skip_old_or_duplicated_advertisement(
        self, new_packet_id: int, adv_time: float
    ) -> bool:
        # no history, first packet, don't discard packet
        if self.last_packet_id is None or self.last_adv_time is None:
            logger.debug(
                f"First packet, not filtering packet_id {new_packet_id}",
            )
            return False

        # more than 4 seconds since last packet, don't discard packet
        if adv_time - self.last_adv_time > 4:
            logger.debug(
                "Not filtering packet_id, more than 4 seconds since last packet. "
                f"New time: {adv_time}, Old time: {self.last_adv_time}"
            )
            return False

        # distance between new packet and old packet is less then 64
        if (
            new_packet_id > self.last_packet_id
            and new_packet_id - self.last_packet_id < 64
        ) or (
            new_packet_id < self.last_packet_id
            and new_packet_id + 256 - self.last_packet_id < 64
        ):
            return False

        # discard packet (new_packet_id=last_packet_id or older packet)
        logger.debug(
            f"New packet_id {new_packet_id} indicates an older packet (previous packet_id {self.last_packet_id}). "
            "BLE advertisement will be skipped"
        )
        return True

    def _parse_payload(self, payload: bytes, adv_time: float, address: str):
        payload_length = len(payload)
        next_obj_start = 0
        prev_obj_meas_type = 0
        measurements: list[dict[str, Any]] = []
        obj_data_format: str | int

        # Create a list with all individual objects
        while payload_length >= next_obj_start + 1:
            obj_start = next_obj_start

            # BTHome V2
            obj_meas_type = payload[obj_start]
            if prev_obj_meas_type > obj_meas_type:
                logger.warning(
                    "BTHome device is not sending object ids in numerical order (from low "
                    "to high object id). This can cause issues with your BTHome receiver, "
                    f"payload: {payload.hex()}]"
                )
            if obj_meas_type not in MEAS_TYPES:
                logger.error(f"Invalid Object ID found in payload: {payload.hex()}")
                break
            prev_obj_meas_type = obj_meas_type
            obj_data_format = MEAS_TYPES[obj_meas_type].data_format

            if obj_data_format in ["raw", "string"]:
                obj_data_length = payload[obj_start + 1]
                obj_data_start = obj_start + 2
            else:
                obj_data_length = MEAS_TYPES[obj_meas_type].data_length
                obj_data_start = obj_start + 1
            next_obj_start = obj_data_start + obj_data_length

            if obj_data_length == 0:
                logger.error(
                    f"Invalid payload data length found with length 0, payload: {payload.hex()}"
                )
                continue

            if payload_length < next_obj_start:
                logger.error(f"Invalid payload data length, payload: {payload.hex()}")
                break

            # Filter BLE advertisements with packet_id that has already been parsed.
            if obj_meas_type == 0:
                new_packet_id = parse_uint(payload[obj_data_start:next_obj_start])
                if self._skip_old_or_duplicated_advertisement(new_packet_id, adv_time):
                    break
                self.last_packet_id = new_packet_id
                self.last_adv_time = adv_time

            measurements.append(
                {
                    "data format": obj_data_format,
                    "data length": obj_data_length,
                    "measurement type": obj_meas_type,
                    "measurement data": payload[obj_data_start:next_obj_start],
                    "device id": None,
                }
            )

        # Parse each object into readable information
        meas_results = {}
        for meas in measurements:
            if meas["measurement type"] not in MEAS_TYPES:
                logger.error(
                    f"UNKNOWN measurement type {meas['measurement type']} in BTHome BLE payload! Adv: {payload.hex()}"
                )
                continue

            meas_type = MEAS_TYPES[meas["measurement type"]]
            meas_factor = meas_type.factor

            value: None | str | int | float | datetime
            if meas["data format"] == 0 or meas["data format"] == "unsigned_integer":
                value = parse_uint(meas["measurement data"], meas_factor)
            elif meas["data format"] == 1 or meas["data format"] == "signed_integer":
                value = parse_int(meas["measurement data"], meas_factor)
            elif meas["data format"] == 2 or meas["data format"] == "float":
                value = parse_float(meas["measurement data"], meas_factor)
            elif meas["data format"] == 3 or meas["data format"] == "string":
                value = parse_string(meas["measurement data"])
            elif meas["data format"] == 4 or meas["data format"] == "raw":
                value = parse_raw(meas["measurement data"])
            elif meas["data format"] == 5 or meas["data format"] == "timestamp":
                value = parse_timestamp(meas["measurement data"])
            else:
                logger.error(
                    f"UNKNOWN dataobject in BTHome BLE payload! Adv: {payload.hex()}"
                )
                continue

            if value is not None:
                if address not in meas_results:
                    meas_results[address] = {}

                meas_results[address][meas_type.state_name] = {
                    "unit": str(meas_type.unit),
                    "value": value,
                    "state_name": meas_type.state_name,
                }

        return meas_results

    def _parse_bthome_v2(
        self, service_info: BLEDevice, service_data: bytes, adv_time: float
    ):
        adv_info = service_data[0]

        # Determine if encryption is used
        encryption = adv_info & (1 << 0)  # bit 0
        if encryption == 1:
            logger.error(f"Sensor is encrypted")
            return False

        # If True, the first 6 bytes contain the mac address
        mac_included = adv_info & (1 << 1)  # bit 1
        if mac_included:
            bthome_mac_reversed = service_data[1:7]
            self.mac_readable = to_mac(bthome_mac_reversed[::-1])
            payload = service_data[7:]
        else:
            self.mac_readable = service_info.address
            payload = service_data[1:]

        # If True, the device is only updating when triggered
        self.sleepy_device = bool(adv_info & (1 << 2))  # bit 2

        # Check BTHome version
        sw_version = (adv_info >> 5) & 7  # 3 bits (5-7)
        if sw_version != 2:
            logger.error(
                f"Sensor is set to use BTHome version {sw_version}, which is not supported"
            )
            return False

        return self._parse_payload(payload, adv_time, service_info.address)

    def detection_callback(self, device: BLEDevice, advertisement: AdvertisementData):
        if device.address.lower() in self.addresses:
            for uuid, service_data in advertisement.service_data.items():
                if uuid.lower() == "0000fcd2-0000-1000-8000-00805f9b34fb":
                    meas_results = self._parse_bthome_v2(
                        device, service_data, time.time()
                    )
                    if meas_results and self.callback:
                        self.callback(meas_results)


if __name__ == "__main__":
    from pprint import pprint

    loop = asyncio.get_event_loop()

    def bthome_callback(data):
        pprint(data)

    async def scan():
        scanner = BTHomeBaseScanner(
            ["7C:C6:B6:61:E5:68", "7C:C6:B6:65:75:A1"], callback=bthome_callback
        )
        await scanner.start()

    asyncio.ensure_future(scan())
    loop.run_forever()
