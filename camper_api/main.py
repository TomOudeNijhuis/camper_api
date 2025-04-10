from fastapi import Depends, FastAPI, HTTPException, Request
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
from sqlalchemy import delete
import asyncio
import logging
from datetime import datetime, timedelta
from typing import cast

from . import crud, models, schemas
from .database import engine, get_db
from .plugins.victron_scanner import VictronScanner
from .plugins.hymer_serial import HymerSerial
from .plugins.bthome_scanner import BTHomeScanner
from .plugins.api_bleak_scanner import ApiBleakScanner
from .plugins.questdb_uploader import QuestDbUploader

from .memory_cache import MemoryCache
from .config import settings


logger = logging.getLogger("uvicorn.camper-api.main")
logging.basicConfig()
logger.setLevel(logging.INFO)

models.Base.metadata.create_all(bind=engine)


class DeleteOldStates:
    def __init__(self):
        self._db = next(get_db())

    async def process_task(self):
        while 1:
            delete_threshold = (
                datetime.now() - timedelta(days=settings.state_delete_after_days)
            ).replace(microsecond=0)
            logger.info(f"Deleting data older than {delete_threshold}")

            self._db.query(models.State).filter(
                models.State.created < delete_threshold
            ).delete()
            self._db.commit()

            await asyncio.sleep(settings.state_delete_interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    api_bleak_scanner = ApiBleakScanner()
    victron_scanner = VictronScanner()
    api_bleak_scanner.add_callback(victron_scanner.detection_callback)
    bthome_scanner = BTHomeScanner()
    api_bleak_scanner.add_callback(bthome_scanner.scanner.detection_callback)
    hymer_serial = HymerSerial()
    delete_old_tasks = DeleteOldStates()
    questdb_uploader = QuestDbUploader()

    MemoryCache.init()

    asyncio.create_task(delete_old_tasks.process_task())
    asyncio.create_task(victron_scanner.process_task())
    asyncio.create_task(hymer_serial.process_task())
    asyncio.create_task(bthome_scanner.process_runner())
    asyncio.create_task(questdb_uploader.process_runner())

    await api_bleak_scanner.start()

    yield {
        "victron_scanner": victron_scanner,
        "hymer_serial": hymer_serial,
        "bthome_scanner": bthome_scanner,
    }


app = FastAPI(lifespan=lifespan)


@app.get("/sensors/", response_model=list[schemas.Sensor])
def read_sensors(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    sensors = crud.get_sensors(db, skip=skip, limit=limit)
    return sensors


@app.get("/sensors/{sensor_id}", response_model=schemas.Sensor)
def read_sensor(sensor_id: int, db: Session = Depends(get_db)):
    db_sensor = crud.get_sensor(db, sensor_id=sensor_id)
    if db_sensor is None:
        raise HTTPException(status_code=404, detail="Sensor not found")
    return db_sensor


@app.put("/sensors/{sensor_id}", response_model=schemas.Sensor)
def update_sensor(
    request: Request,
    sensor_id: int,
    sensor: schemas.SensorUpdate,
    db: Session = Depends(get_db),
):
    db_sensor = crud.get_sensor(db, sensor_id)
    if db_sensor is None:
        raise HTTPException(status_code=404, detail="Sensor not found")

    crud.update_sensor(db, sensor_id, sensor)

    db.refresh(db_sensor)

    # Update device data in ble scanner
    scanner = cast(VictronScanner, request.state.victron_scanner)
    scanner.remove_device(db_sensor.address)

    entities = {e.name: e.id for e in db_sensor.entities}
    scanner.add_device(db_sensor.address, db_sensor.key, entities)

    return db_sensor


@app.post("/sensors/", response_model=schemas.Sensor)
def create_sensor(
    request: Request, sensor: schemas.SensorCreate, db: Session = Depends(get_db)
):
    db_sensor = crud.get_sensor_by_name(db, sensor.name)
    if db_sensor:
        raise HTTPException(
            status_code=400, detail=f"Sensor with name {sensor.name} already registered"
        )

    db_sensor = crud.create_sensor(db, sensor)

    # Update device data in ble scanner
    scanner = cast(VictronScanner, request.state.victron_scanner)

    entities = {e.name: e.id for e in db_sensor.entities}
    scanner.add_device(db_sensor.address, db_sensor.key, entities)

    return db_sensor


@app.delete("/sensors/{sensor_id}", response_model=dict)
async def delete_sensor(
    request: Request,
    sensor_id: int,
    db: Session = Depends(get_db),
):
    db_sensor = crud.get_sensor(db, sensor_id)
    if db_sensor is None:
        raise HTTPException(status_code=404, detail=f"Sensor {sensor_id} not found")

    # Update device data in ble scanner
    scanner = cast(VictronScanner, request.state.victron_scanner)
    scanner.remove_device(db_sensor.address)

    db.delete(db_sensor)
    db.commit()

    return {"message": f"Sensor {sensor_id} removed."}


@app.get("/sensors/{sensor_id_name}/entities/", response_model=list[schemas.Entity])
def read_entities_by_sensor_id_or_name(
    sensor_id_name: str, db: Session = Depends(get_db)
):
    try:
        sensor_id = int(sensor_id_name)
    except ValueError:
        sensor = crud.get_sensor_by_name(db, sensor_id_name)
        if sensor is None:
            raise HTTPException(
                status_code=404, detail=f"Sensor {sensor_id_name} not found"
            )
        sensor_id = sensor.id

    entities = crud.get_entities_by_sensor(db, sensor_id)
    return entities


@app.get("/sensors/{sensor_id_name}/states/", response_model=list[schemas.State])
async def read_sensor_states_by_sensor_id_or_name(
    sensor_id_name: str, db: Session = Depends(get_db)
):
    try:
        sensor_id = int(sensor_id_name)
    except ValueError:
        sensor = crud.get_sensor_by_name(db, sensor_id_name)
        if sensor is None:
            raise HTTPException(
                status_code=404, detail=f"Sensor {sensor_id_name} not found"
            )
        sensor_id = sensor.id
    """
    FIXME: This one does not use the cache!
    db_states = await crud.get_states_from_sensor(db, sensor_id)
    """
    entities = crud.get_entities_by_sensor(db, sensor_id)

    db_states = []
    for entity in entities:
        db_state = await crud.get_state(db, entity.id)
        if db_state:
            state_model = schemas.State.model_validate(db_state)
            state_model.entity_name = entity.name
            db_states.append(state_model)

    return db_states


@app.get("/entities/{entity_id}", response_model=schemas.Entity)
def read_entity(entity_id: int, db: Session = Depends(get_db)):
    db_entity = crud.get_entity(db, entity_id)
    if db_entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    return db_entity


@app.post("/sensor/{sensor_id}/entities/", response_model=schemas.Entity)
def create_entity(
    request: Request,
    entity: schemas.EntityCreate,
    sensor_id: int,
    db: Session = Depends(get_db),
):
    db_entity = crud.get_entity_by_name(db, sensor_id, entity.name)
    if db_entity:
        raise HTTPException(
            status_code=400,
            detail=f"Entity with name {entity.name} already registered for sensor {sensor_id}",
        )

    db_sensor = crud.get_sensor(db, sensor_id)
    if db_sensor is None:
        raise HTTPException(status_code=404, detail="Sensor not found")

    db_entity = crud.create_entity(db, entity, sensor_id)

    # Update device data in ble scanner
    scanner = cast(VictronScanner, request.state.victron_scanner)
    scanner.add_entity(db_sensor.address, db_entity.name, db_entity.id)

    return db_entity


@app.delete("/entities/{entity_id}", response_model=dict)
async def delete_entity(
    request: Request,
    entity_id: int,
    db: Session = Depends(get_db),
):
    db_entity = crud.get_entity(db, entity_id)
    if db_entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    # Update device data in ble scanner
    scanner = cast(VictronScanner, request.state.victron_scanner)
    scanner.remove_entity(db_entity.sensor.address, db_entity.name)

    db.delete(db_entity)
    db.commit()

    return {"message": f"entity {entity_id} removed."}


@app.get(
    "/entities/{entity_id}/states",
    response_model=list[schemas.State],
    response_model_exclude_unset=True,
    response_model_exclude=["entity_id", "entity_name"],
)
def read_states(
    entity_id: int, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)
):
    db_entity = crud.get_entity(db, entity_id)
    if db_entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    db_states = crud.get_states(db, entity_id=entity_id, skip=skip, limit=limit)

    return db_states


@app.post(
    "/entities/{entity_id}/state",
    response_model=schemas.State,
    response_model_exclude_unset=True,
    response_model_exclude=["entity_id", "entity_name"],
)
async def create_state(state: schemas.StateCreate, db: Session = Depends(get_db)):
    db_state = await crud.create_state(
        db, **state.model_dump(exclude_none=True, exclude_unset=True)
    )

    return db_state


@app.post(
    "/states_by_name/{target_sensor_name}/{target_entity_name}",
    response_model=list[schemas.State],
    response_model_exclude_unset=True,
    response_model_exclude=["entity_id", "entity_name"],
)
async def states_by_sensor_and_entity_name(
    target_sensor_name: str,
    target_entity_name: str,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    db_sensor = crud.get_sensor_by_name(db, target_sensor_name)
    if db_sensor is None:
        raise HTTPException(
            status_code=404, detail=f"Sensor {target_sensor_name} not found"
        )

    db_entity = crud.get_entity_by_name(db, db_sensor.id, target_entity_name)
    if db_entity is None:
        raise HTTPException(
            status_code=404, detail=f"Entity {target_entity_name} not found"
        )

    db_states = crud.get_states(db, entity_id=db_entity.id, skip=skip, limit=limit)

    return db_states


@app.post("/action/{target_entity_id}", response_model=dict)
async def execute_action(
    request: Request,
    target_entity_id: str,
    action_data: dict,
    db: Session = Depends(get_db),
):
    db_entity = crud.get_entity(db, target_entity_id)
    if db_entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    hymer_serial = cast(HymerSerial, request.state.hymer_serial)

    match db_entity.name:
        case "household_state":
            response = await hymer_serial.household(**action_data)
        case "pump_state":
            response = await hymer_serial.pump(**action_data)
        case _:
            raise HTTPException(
                status_code=404, detail=f"Action on entity {db_entity.name} not allowed"
            )

    return response


@app.post(
    "/action_by_name/{target_sensor_name}/{target_entity_name}", response_model=dict
)
async def execute_action_by_name(
    request: Request,
    target_sensor_name: str,
    target_entity_name: str,
    action_data: dict,
    db: Session = Depends(get_db),
):
    db_sensor = crud.get_sensor_by_name(db, target_sensor_name)
    if db_sensor is None:
        raise HTTPException(
            status_code=404, detail=f"Sensor {target_sensor_name} not found"
        )

    db_entity = crud.get_entity_by_name(db, db_sensor.id, target_entity_name)
    if db_entity is None:
        raise HTTPException(
            status_code=404, detail=f"Entity {target_entity_name} not found"
        )

    hymer_serial = cast(HymerSerial, request.state.hymer_serial)

    match db_entity.name:
        case "household_state":
            response = await hymer_serial.household(**action_data)
        case "pump_state":
            response = await hymer_serial.pump(**action_data)
        case _:
            raise HTTPException(
                status_code=404, detail=f"Action on entity {db_entity.name} not allowed"
            )

    return response
