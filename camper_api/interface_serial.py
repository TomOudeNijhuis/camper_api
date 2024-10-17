import asyncio
import logging
import serial
from datetime import datetime

from .config import settings
from .database import get_db
from . import crud, schemas, models

logger = logging.getLogger("camper-api")

CAMPER_ENTITIES = [
    "household_voltage",
    "starter_voltage",
    "mains_voltage",
    "household_state",
    "water_state",
    "waste_state",
    "pump_state",
]


class InterfaceSerial:
    def __init__(self):
        self._serial = serial.Serial(
            settings.interface_serial_port,
            settings.interface_serial_speed,
            timeout=settings.interface_serial_timeout,
        )

        self._db = next(get_db())

        self.sensor = crud.get_sensor_by_name(self._db, "camper")
        if self.sensor is None:
            self.sensor = crud.create_sensor(
                self._db, schemas.SensorCreate(name="camper")
            )

        entities = crud.get_entities_by_sensor(self._db, self.sensor.id)
        self.entities_by_name = {e.name: e for e in entities}

        for entity_name in CAMPER_ENTITIES:
            if entity_name not in self.entities_by_name.keys():
                entity = crud.create_entity(
                    self._db, schemas.EntityCreate(name=entity_name), self.sensor.id
                )
                self.entities_by_name[entity_name] = entity

        print(self.entities_by_name)

    def _command(self, cmd, param):
        self._serial.flushInput()

        instruction = f"{cmd} {param}\r\n".encode("ascii")
        self._serial.write(instruction)
        resp = self._serial.readline()

        if instruction != resp:
            raise Exception(f"No echo or echo not matching: {resp}")

        resp = self._serial.readline()

        if not resp:
            raise Exception("No response")

        resp_sections = resp.decode("ascii").strip().split(" ")
        if len(resp_sections) != 2:
            raise Exception(
                f"Expected cmd and param for response but received {len(resp_sections)} items."
            )

        if resp_sections[0] != cmd:
            raise Exception(
                f"Command in request {cmd} and response {resp_sections[0]} do not match!"
            )

        _, v = resp_sections[1].split("=")

        print(cmd, v)

        return v

    async def _store_state(self, entity_name, state):
        await crud.create_state(self._db, self.entities_by_name[entity_name].id, state)

    async def process_task(self):
        while 1:
            try:
                value = self._command("VOLTAGE", "household")
                await self._store_state("household_voltage", value)

                value = self._command("VOLTAGE", "starter")
                await self._store_state("starter_voltage", value)

                value = self._command("VOLTAGE", "mains")
                await self._store_state("mains_voltage", value)

                value = self._command("HOUSEHOLD", "?")
                await self._store_state("household_state", value)

                value = self._command("WATER", "?")
                await self._store_state("water_state", value)

                value = self._command("WASTE", "?")
                await self._store_state("waste_state", value)

                value = self._command("PUMP", "?")
                await self._store_state("pump_state", value)
            except Exception as ex:
                logger.error("Error processing", exc_info=True)

            await asyncio.sleep(settings.state_responsive_sample_interval)

    def household(self, state):
        new_state = self._command("HOUSEHOLD", str(state))
        self._store_state("household_state", new_state)

        return {"state": new_state}

    def pump(self, state):
        new_state = self._command("PUMP", str(state))
        self._store_state("pump_state", new_state)

        return {"state": new_state}


if __name__ == "__main__":
    interface_serial = InterfaceSerial()

    print(interface_serial._command("HOUSEHOLD", "0"))
