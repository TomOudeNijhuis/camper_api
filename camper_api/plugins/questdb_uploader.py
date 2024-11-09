import logging
import asyncio
from datetime import datetime
from aiohttp import ClientSession, ClientTimeout, FormData
import csv
import io

from ..config import settings
from ..database import get_db
from .. import crud

logger = logging.getLogger("camper-api")

"""
CREATE TABLE states (
    ts TIMESTAMP,
    sensor SYMBOL,
    entity SYMBOL,
    state STRING
) TIMESTAMP(ts) PARTITION BY WEEK WAL
DEDUP UPSERT KEYS(ts, sensor, entity);

"""


class QuestImportException(Exception):
    pass


class QuestDbUploader:
    def __init__(self):
        self._db = next(get_db())

    async def upload_chunk(self, states):
        timeout = ClientTimeout(total=10)
        async with ClientSession(timeout=timeout) as session:
            for state in states:
                async with session.get(
                    settings.questdb_config,
                    params={
                        "query": (
                            f"INSERT INTO states (ts, sensor, entity, state) "
                            f"VALUES ('{state.created.isoformat()}', '{state.entity.sensor.name}', '{state.entity.name}', '{state.state}');"
                        )
                    },
                ) as response:
                    resp_json = await response.json()

                    if response.status != 200:
                        raise QuestImportException(
                            f"Failed to upload state: {response.status}"
                        )
                    if resp_json.get("dml") != "OK":
                        raise QuestImportException(
                            f"Failed to upload state: {resp_json}"
                        )

    async def get_last_upload(self):
        last_upload_str = await crud.get_parameter_value(self._db, "last_upload")

        if last_upload_str:
            return datetime.fromisoformat(last_upload_str)
        else:
            return None

    async def set_last_upload(self, stamp):
        await crud.set_parameter_value(
            self._db,
            "last_upload",
            stamp.isoformat(),
        )

    async def process_runner(self):
        await asyncio.sleep(settings.questdb_startup_delay)

        while 1:
            try:
                # await self.set_last_upload(datetime(2000, 1, 1))
                last_upload = await self.get_last_upload()
                new_last_upload = None
                upload_started = datetime.now()
                print(f"last_upload: {last_upload}, upload_started {upload_started}")

                states = None
                while (
                    states is None or len(states) == settings.questdb_startup_chunk_size
                ) and (
                    datetime.now() - upload_started
                ).total_seconds() < settings.questdb_upload_timeout:
                    x = 0 if states is None else x + settings.questdb_startup_chunk_size

                    states = crud.get_states(
                        self._db,
                        skip=x,
                        limit=settings.questdb_startup_chunk_size,
                        after=last_upload,
                    )
                    if states:
                        await self.upload_chunk(states)
                        new_last_upload = states[-1].created

                    print(
                        f"Runtime: {(datetime.now() - upload_started).total_seconds()}; "
                        f"Chunk: {int(x / settings.questdb_startup_chunk_size)}; "
                        f"Last chunksize: {len(states)}."
                    )

                if new_last_upload:
                    await self.set_last_upload(new_last_upload)

            except QuestImportException:
                print("QuestImportException")
                logger.error("QuestImportException", exc_info=True)

            except Exception:
                print("Exception")
                logger.error("Exception", exc_info=True)

            await asyncio.sleep(settings.questdb_upload_interval)
