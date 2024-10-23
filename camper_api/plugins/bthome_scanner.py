import asyncio
import logging

from ..config import settings
from ..database import get_db
from .. import crud, schemas
from .bthome_bleak import BTHomeBaseScanner

logger = logging.getLogger("camper-api")


class BTHomeScanner:
    def __init__(self):
        self._db = next(get_db())
        self.entity_id_by_name = {}
        self.state_cache = {}

        for sensor_name, sensor_mac in settings.bthome_sensors.items():
            sensor = crud.get_sensor_by_name(self._db, sensor_name)
            if sensor is None:
                sensor = crud.create_sensor(
                    self._db, schemas.SensorCreate(name=sensor_name, address=sensor_mac)
                )

            entities = crud.get_entities_by_sensor(self._db, sensor.id)
            self.entity_id_by_name[sensor_mac] = {e.name: e.id for e in entities}

            for entity_name in settings.bthome_entities[sensor_name]:
                if entity_name not in self.entity_id_by_name[sensor_mac].keys():
                    entity = crud.create_entity(
                        self._db, schemas.EntityCreate(name=entity_name), sensor.id
                    )
                    self.entity_id_by_name[sensor_mac][entity_name] = entity.id

        self.scanner = BTHomeBaseScanner(
            self.entity_id_by_name.keys(), callback=self._bthome_callback
        )

    async def start(self):
        await self.scanner.start()

    def _bthome_callback(self, bthome_data):
        for sensor_mac, data in bthome_data.items():
            for entity_name, state in data.items():
                if entity_name in self.entity_id_by_name[sensor_mac].keys():
                    entity_id = self.entity_id_by_name[sensor_mac][entity_name]
                    self.state_cache[entity_id] = state["value"]

    async def process_runner(self):
        while 1:
            for entity_id, state in self.state_cache.items():
                await crud.create_state(self._db, entity_id, str(state))

            await asyncio.sleep(settings.state_monitor_sample_interval)
