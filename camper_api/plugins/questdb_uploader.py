from questdb.ingress import Sender, IngressError
import sys
import logging
import asyncio
from datetime import datetime

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


class QuestDbUploader:
    def __init__(self):
        self._db = next(get_db())

    def upload_chunk(self, sender, states):
        for di in states:
            sender.row(
                "states",
                symbols={"sensor": di.entity.sensor.name, "entity": di.entity.name},
                columns={
                    "state": di.state,
                },
                at=di.created,
            )

        sender.flush()

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
                last_upload = await self.get_last_upload()
                new_last_upload = None
                upload_started = datetime.now()
                print(f"last_upload: {last_upload}, upload_started {upload_started}")

                states = None
                with Sender.from_conf(settings.questdb_config) as sender:
                    while (states is None or len(states) == 100) and (
                        datetime.now() - upload_started
                    ).total_seconds() < settings.questdb_upload_timeout:
                        x = 0 if states is None else x + 100

                        states = crud.get_states(
                            self._db, skip=x, limit=100, after=last_upload
                        )
                        if states:
                            self.upload_chunk(sender, states)
                            new_last_upload = states[-1].created

                        print(
                            f"Running for {(datetime.now() - upload_started).total_seconds()} on state number {x}."
                        )

                if new_last_upload:
                    await self.set_last_upload(new_last_upload)

            except IngressError:
                logger.error("IngressError", exc_info=True)

            except Exception:
                logger.error("Exception", exc_info=True)

            await asyncio.sleep(settings.questdb_upload_interval)
