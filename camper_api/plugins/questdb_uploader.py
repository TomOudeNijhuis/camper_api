import logging
import asyncio
from datetime import datetime
from aiohttp import ClientSession, ClientTimeout
from aiohttp import ClientSession, ClientTimeout

try:
    from questdb.ingress import Sender, IngressError

    PROTOCOL = "ilp"
except ImportError:
    PROTOCOL = "rest"

from ..config import settings
from ..database import get_db
from .. import crud

logger = logging.getLogger("uvicorn.camper-api.questdb_uploader")

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
        self._active_config = None

    async def _get_active_config(self):
        timeout = ClientTimeout(total=10)
        async with ClientSession(timeout=timeout) as session:
            for config in settings.questdb_configs:
                try:
                    config_str = (
                        f"http://{settings.questdb_user}:{settings.questdb_password}"
                        f"@{config['host']}:{config['port']}/exec"
                    )
                    async with session.get(
                        config_str,
                        params={"query": "select count(*), MAX(ts) FROM states;"},
                    ) as response:
                        resp_json = await response.json()
                        count, max = resp_json["dataset"][0]
                        logger.info(f"States count: {count}; Latest entry: {max}")

                    if PROTOCOL == "ilp":
                        self._active_config = (
                            f"http::addr={config["host"]}:{config["port"]};"
                            f"username={settings.questdb_user};password={settings.questdb_password};"
                        )
                    else:
                        self._active_config = config_str

                    return

                except Exception:
                    pass

        raise QuestImportException("Cannot connect to questdb server.")

    def _upload_chunk_ilp(self, sender, states):
        try:
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
        except IngressError as ex:
            raise QuestImportException(f"IngressError: {ex}")

    async def _upload_chunk_rest(self, session, states):
        for state in states:
            async with session.get(
                self._active_config,
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
                    raise QuestImportException(f"Failed to upload state: {resp_json}")

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

    def _process_loop_ilp(self, session_sender, started, last_upload):
        new_last_upload = None
        states = None

        while (
            states is None or len(states) == settings.questdb_startup_chunk_size
        ) and (
            datetime.now() - started
        ).total_seconds() < settings.questdb_upload_timeout:
            if states is None:
                x = 0
            else:
                x = x + settings.questdb_startup_chunk_size

            states = crud.get_states(
                self._db,
                skip=x,
                limit=settings.questdb_startup_chunk_size,
                after=last_upload,
            )
            if states:
                self._upload_chunk_ilp(session_sender, states)
                new_last_upload = states[-1].created

            logger.info(
                f"Runtime: {(datetime.now() - started).total_seconds()}; "
                f"Chunk: {int(x / settings.questdb_startup_chunk_size)}; "
                f"Last chunksize: {len(states)}."
            )

        return new_last_upload

    async def _process_loop_rest(self, session_sender, started, last_upload):
        new_last_upload = None
        states = None

        while (
            states is None or len(states) == settings.questdb_startup_chunk_size
        ) and (
            datetime.now() - started
        ).total_seconds() < settings.questdb_upload_timeout:
            if states is None:
                x = 0
            else:
                x = x + settings.questdb_startup_chunk_size

            states = crud.get_states(
                self._db,
                skip=x,
                limit=settings.questdb_startup_chunk_size,
                after=last_upload,
            )
            if states:
                await self._upload_chunk_rest(session_sender, states)
                new_last_upload = states[-1].created

            logger.info(
                f"Runtime: {(datetime.now() - started).total_seconds()}; "
                f"Chunk: {int(x / settings.questdb_startup_chunk_size)}; "
                f"Last chunksize: {len(states)}."
            )

        return new_last_upload

    async def process_runner(self):
        await asyncio.sleep(settings.startup_delay)

        while 1:
            started = datetime.now()
            try:
                await self._get_active_config()
                last_upload = await self.get_last_upload()

                logger.info(
                    f"last_upload: {last_upload}, upload_started {started}, config: {self._active_config}"
                )

                if PROTOCOL == "ilp":
                    with Sender.from_conf(self._active_config) as session_sender:
                        new_last_upload = self._process_loop_ilp(
                            session_sender, started, last_upload
                        )

                else:
                    timeout = ClientTimeout(total=10)
                    async with ClientSession(timeout=timeout) as session_sender:
                        new_last_upload = await self._process_loop_rest(
                            session_sender, started, last_upload
                        )

                if new_last_upload:
                    await self.set_last_upload(new_last_upload)

            except QuestImportException:
                logger.error("QuestImportException", exc_info=True)

            except Exception:
                logger.error("Exception", exc_info=True)

            wait_time = (
                settings.questdb_upload_interval
                - (datetime.now() - started).total_seconds()
            )
            if wait_time > 0:
                await asyncio.sleep(wait_time)
