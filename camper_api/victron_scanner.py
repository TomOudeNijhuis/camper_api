from victron_ble.scanner import BaseScanner
from victron_ble.exceptions import AdvertisementKeyMissingError, UnknownDeviceError
from victron_ble.devices import Device, detect_device_type
from bleak.backends.device import BLEDevice
import inspect
from enum import Enum


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


class VictronScanner(BaseScanner):
    def __init__(self):
        super().__init__()
        self._devices = {}
        self._known_devices: dict[str, Device] = {}
        self._latest_entity_data = {}

    async def start(self):
        await super().start()

    def add_device(self, address, key, entities):
        if address.lower() in self._devices:
            raise Exception(f"Device {address.lower()} already present")

        self._devices[address.lower()] = {
            "key": key,
            "entities": entities,
        }

    def remove_device(self, address):
        if address.lower() not in self._devices:
            raise Exception(f"Device {address.lower()} is not present")

        for entity_id in self._devices[address.lower()]["entities"].values():
            if entity_id in self._latest_entity_data:
                del self._latest_entity_data[entity_id]

        del self._devices[address.lower()]

        if address.lower() in self._known_devices:
            del self._known_devices[address.lower()]

    def add_entity(self, device_address, entity_name, entity_id):
        if device_address.lower() not in self._devices:
            raise Exception(f"Device {device_address.lower()} is not present")

        self._devices[device_address.lower()]["entities"][entity_name] = entity_id

    def remove_entity(self, device_address, entity_name):
        if device_address.lower() not in self._devices:
            raise Exception(f"Device {device_address.lower()} is not present")

        if entity_name not in self._devices[device_address.lower()]["entities"]:
            raise Exception(
                f"Device {device_address.lower()} does not have entity {entity_name}"
            )

        del self._devices[device_address.lower()]["entities"][entity_name]

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

    def callback(self, ble_device: BLEDevice, raw_data: bytes):
        # print(f"Received data from {ble_device.address.lower()}: {raw_data.hex()}")
        try:
            device = self.get_device(ble_device, raw_data)
        except AdvertisementKeyMissingError:
            return
        except UnknownDeviceError as e:
            print(f"Unknown device {str(e)}")
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
                raise Exception(
                    f"Unsupported entity {name} for device {ble_device.address.lower()}"
                )

    def get_entity_data(self):
        entity_data = self._latest_entity_data.copy()
        self._latest_entity_data = {}

        return entity_data
