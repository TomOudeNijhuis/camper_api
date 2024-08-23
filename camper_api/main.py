from fastapi import Depends, FastAPI, HTTPException, Request
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
from sqlalchemy import delete
import asyncio
import logging
from datetime import datetime, timedelta
from typing import cast

from . import crud, models, schemas
from .database import SessionLocal, engine
from .victron_scanner import VictronScanner
from .config import settings


logger = logging.getLogger("victron_ble")
logging.basicConfig()
logger.setLevel(logging.DEBUG)

models.Base.metadata.create_all(bind=engine)


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class DeleteOldStates:
    def __init__(self):
        self._db = next(get_db())

    async def process_task(self):
        while 1:
            delete_threshold = (datetime.now() - timedelta(days=10)).replace(
                microsecond=0
            )
            print(f"Deleting data older than {delete_threshold}")

            self._db.query(models.State).filter(
                models.State.created < delete_threshold
            ).delete()
            self._db.commit()

            await asyncio.sleep(settings.state_delete_interval)


class ProcessVictronData:
    def __init__(self, scanner: VictronScanner):
        self._scanner = scanner
        self._db = next(get_db())

        self.add_sensors()

    def add_sensors(self):
        sensors = self._db.query(models.Sensor).all()

        for sensor in sensors:
            entities = {e.name: e.id for e in sensor.entities}
            self._scanner.add_device(sensor.address, sensor.key, entities)

    async def process_task(self):
        while 1:
            entity_data = self._scanner.get_entity_data()

            for entity_id, entity_state in entity_data.items():
                db_item = models.State(
                    entity_id=entity_id,
                    state=entity_state,
                    created=datetime.now().replace(microsecond=0),
                )
                self._db.add(db_item)
                self._db.commit()

            await asyncio.sleep(settings.state_sample_interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scanner = VictronScanner()
    processor_victron_data = ProcessVictronData(scanner)
    delete_old_tasks = DeleteOldStates()

    asyncio.create_task(delete_old_tasks.process_task())
    asyncio.create_task(processor_victron_data.process_task())
    await scanner.start()

    yield {"victron_scanner": scanner}


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
    db_sensor = crud.get_sensor(db, sensor_id=sensor_id)
    if db_sensor is None:
        raise HTTPException(status_code=404, detail="Sensor not found")

    crud.update_sensor(db=db, sensor_id=sensor_id, sensor=sensor)

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
    db_sensor = crud.get_sensor_by_name(db, sensor_name=sensor.name)
    if db_sensor:
        raise HTTPException(
            status_code=400, detail=f"Sensor with name {sensor.name} already registered"
        )

    db_sensor = crud.create_sensor(db=db, sensor=sensor)

    # Update device data in ble scanner
    scanner = cast(VictronScanner, request.state.victron_scanner)

    entities = {e.name: e.id for e in db_sensor.entities}
    scanner.add_device(db_sensor.address, db_sensor.key, entities)

    return db_sensor


@app.get("/sensors/{sensor_id}/entities/", response_model=list[schemas.Entity])
def read_entities(sensor_id: int, db: Session = Depends(get_db)):
    sensors = crud.get_entities_by_sensor(db, sensor_id)
    return sensors


@app.get("/entities/{entity_id}", response_model=schemas.Entity)
def read_entity(entity_id: int, db: Session = Depends(get_db)):
    db_entity = crud.get_entity(db, entity_id=entity_id)
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
    db_entity = crud.get_entity_by_name(
        db, sensor_id=sensor_id, entity_name=entity.name
    )
    if db_entity:
        raise HTTPException(
            status_code=400,
            detail=f"Entity with name {entity.name} already registered for sensor {sensor_id}",
        )

    db_sensor = crud.get_sensor(db=db, sensor_id=sensor_id)
    if db_sensor is None:
        raise HTTPException(status_code=404, detail="Sensor not found")

    db_entity = crud.create_entity(db=db, entity=entity, sensor_id=sensor_id)

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
    db_entity = crud.get_entity(db, entity_id=entity_id)
    if db_entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    # Update device data in ble scanner
    scanner = cast(VictronScanner, request.state.victron_scanner)
    scanner.remove_entity(db_entity.sensor.address, db_entity.name)

    db.delete(db_entity)
    db.commit()

    return {"message": "entity removed."}


@app.get("/entities/{entity_id}/states", response_model=list[schemas.State])
def read_state(
    entity_id: int, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)
):
    db_entity = crud.get_entity(db, entity_id=entity_id)
    if db_entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    db_states = crud.get_states(db, entity_id=entity_id, skip=skip, limit=limit)

    return db_states
