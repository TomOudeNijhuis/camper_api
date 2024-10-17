from sqlalchemy.orm import Session
from sqlalchemy import and_, update
from datetime import datetime, timedelta

from . import models, schemas
from .memory_cache import MemoryCache
from .config import settings


def get_sensors(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Sensor).offset(skip).limit(limit).all()


def get_sensor(db: Session, sensor_id: int):
    return db.query(models.Sensor).filter(models.Sensor.id == sensor_id).first()


def get_sensor_by_name(db: Session, sensor_name: str):
    return db.query(models.Sensor).filter(models.Sensor.name == sensor_name).first()


def update_sensor(db: Session, sensor_id: str, sensor: schemas.SensorUpdate):
    db.execute(
        update(models.Sensor)
        .filter_by(id=sensor_id)
        .values(sensor.model_dump(exclude_none=True, exclude_unset=True))
    )
    db.commit()


def create_sensor(db: Session, sensor: schemas.SensorCreate):
    db_sensor = models.Sensor(
        **sensor.model_dump(exclude_none=True, exclude_unset=True)
    )
    db.add(db_sensor)
    db.commit()
    db.refresh(db_sensor)
    return db_sensor


def get_entities_by_sensor(db: Session, sensor_id: int):
    return db.query(models.Entity).filter(models.Entity.sensor_id == sensor_id).all()


def get_entity(db: Session, entity_id: int):
    return db.query(models.Entity).filter(models.Entity.id == entity_id).first()


def get_entity_by_name(db: Session, sensor_id: int, entity_name: str):
    return (
        db.query(models.Entity)
        .filter(
            and_(
                models.Entity.name == entity_name, models.Entity.sensor_id == sensor_id
            )
        )
        .first()
    )


def create_entity(db: Session, entity: schemas.EntityCreate, sensor_id: int):
    db_entity = models.Entity(
        **entity.model_dump(exclude_none=True, exclude_unset=True), sensor_id=sensor_id
    )
    db.add(db_entity)
    db.commit()
    db.refresh(db_entity)
    return db_entity


def get_states(db: Session, entity_id: int, skip: int = 0, limit: int = 100):
    return (
        db.query(models.State)
        .filter(models.State.entity_id == entity_id)
        .offset(skip)
        .limit(limit)
        .all()
    )


async def create_state(db: Session, entity_id: int, state: str):
    stamp = datetime.now().replace(microsecond=0)

    backend = MemoryCache.get_backend()
    cache_state, cache_created = await backend.get(f"state_{entity_id}")

    await backend.set(
        f"state_{entity_id}", state, stamp, settings.state_storage_interval
    )

    if cache_state is None:
        db_item = models.State(
            entity_id=entity_id,
            state=state,
            created=stamp,
        )
        db.add(db_item)
        db.commit()

        return db_item
    else:
        return schemas.State(entity_id=entity_id, state=state, created=stamp)


async def get_state(db: Session, entity_id: int):
    backend = MemoryCache.get_backend()
    cache_state, cache_created = await backend.get(f"state_{entity_id}")

    if cache_state:
        return schemas.State(
            entity_id=entity_id, state=cache_state, created=cache_created
        )

    db_query = db.query(models.State).filter(models.State.entity_id == entity_id)

    age_threshold = datetime.now() - timedelta(minutes=5)
    db_query = db_query.filter(models.State.created > age_threshold)

    return db_query.order_by(models.State.created.desc()).first()
