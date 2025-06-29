from victron_ble.exceptions import AdvertisementKeyMissingError, UnknownDeviceError
from victron_ble.devices import Device, detect_device_type
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
import inspect
from enum import Enum
import asyncio
from typing import Set
import logging

from ..config import settings
from ..database import get_db
from .. import crud, schemas

logger = logging.getLogger("uvicorn.camper-api.victron_scanner")


def parse_object_dict(obj):
    data = {}
    for name, method in inspect.getmembers(obj, predicate=inspect.ismethod):
        if name.startswith("get_"):
            value = method()
            if isinstance(value, Enum):
                value = value.name.lower()
            if value is not None:
                data[name[4:]] = value
    return data


class VictronScanner:
    def __init__(self):
        self._seen_data: Set[bytes] = set()
        self._devices = {}
        self._known_devices: dict[str, Device] = {}
        self._latest_entity_data = {}
        self._db = next(get_db())

        for sensor_name, sensor_details in settings.victron_sensors.items():
            sensor = crud.get_sensor_by_name(self._db, sensor_name)
            if sensor is None:
                sensor = crud.create_sensor(
                    self._db,
                    schemas.SensorCreate(
                        name=sensor_name,
                        address=sensor_details["address"].lower(),
                        key=sensor_details["key"],
                    ),
                )

            self._devices[sensor.address.lower()] = {
                "key": sensor.key,
                "entities": {},
            }

            entities = crud.get_entities_by_sensor(self._db, sensor.id)
            self._devices[sensor.address.lower()]["entities"] = {
                e.name: e.id for e in entities
            }

            for entity_name in settings.victron_entities[sensor.name]:
                if (
                    entity_name
                    not in self._devices[sensor.address.lower()]["entities"].keys()
                ):
                    entity = crud.create_entity(
                        self._db, schemas.EntityCreate(name=entity_name), sensor.id
                    )
                    self._devices[sensor.address.lower()]["entities"][entity_name] = (
                        entity.id
                    )

    def get_device(self, ble_device: BLEDevice, raw_data: bytes) -> Device:
        address = ble_device.address.lower()
        if address not in self._known_devices:
            advertisement_key = self.load_key(address)

            device_klass = detect_device_type(raw_data)
            if not device_klass:
                raise UnknownDeviceError(
                    f"Could not identify device type for {ble_device}"
                )

            self._known_devices[address] = device_klass(advertisement_key)

        return self._known_devices[address]

    def load_key(self, address: str) -> str:
        try:
            return self._devices[address]["key"]
        except KeyError:
            raise AdvertisementKeyMissingError(f"No key available for {address}")

    def detection_callback(
        self, ble_device: BLEDevice, advertisement: AdvertisementData
    ):
        raw_data = advertisement.manufacturer_data.get(0x02E1)
        if (
            not raw_data
            or not raw_data.startswith(b"\x10")
            or raw_data in self._seen_data
        ):
            return

        # De-duplicate advertisements
        if len(self._seen_data) > 1000:
            self._seen_data = set()
        self._seen_data.add(raw_data)

        try:
            device = self.get_device(ble_device, raw_data)
        except AdvertisementKeyMissingError:
            return
        except UnknownDeviceError as e:
            logger.error(f"Unknown device {str(e)}")
            return

        parsed = device.parse(raw_data)
        data_dict = parse_object_dict(parsed)

        for name, entity_id in self._devices[ble_device.address.lower()][
            "entities"
        ].items():
            if name == "rssi":
                self._latest_entity_data[entity_id] = ble_device.rssi
            elif name in data_dict:
                self._latest_entity_data[entity_id] = data_dict[name]
            else:
                logger.info(
                    f"Entity {name} not found in data for device {ble_device.address.lower()} at this time."
                )

    async def process_task(self):
        while 1:
            entity_data = self._latest_entity_data.copy()
            self._latest_entity_data = {}

            for entity_id, entity_state in entity_data.items():
                await crud.create_state(self._db, entity_id, str(entity_state))

            await asyncio.sleep(settings.state_monitor_sample_interval)
