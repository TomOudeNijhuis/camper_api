from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData


class ApiBleakScanner:
    def __init__(self):
        self._scanner: BleakScanner = BleakScanner(
            detection_callback=self.detection_callback
        )
        self._callbacks = []

    def detection_callback(
        self, ble_device: BLEDevice, advertisement: AdvertisementData
    ):
        for callback in self._callbacks:
            callback(ble_device, advertisement)

    async def start(self):
        await self._scanner.start()

    async def stop(self):
        await self._scanner.stop()

    def add_callback(self, callback):
        self._callbacks.append(callback)
