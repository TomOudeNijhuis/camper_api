from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class EntityBase(BaseModel):
    name: str
    unit: str | None = None
    description: str | None = None


class EntityCreate(EntityBase):
    pass


class Entity(EntityBase):
    id: int
    sensor_id: int

    class Config:
        from_attributes = True


class SensorBase(BaseModel):
    address: str | None = None
    key: str | None = None


class SensorCreate(SensorBase):
    name: str


class SensorUpdate(SensorBase):
    name: str | None = None


class Sensor(SensorBase):
    id: int
    name: str
    entities: list[Entity] = []

    class Config:
        from_attributes = True


class StateBase(BaseModel):
    entity_id: int
    state: str


class StateCreate(StateBase):
    pass


class State(StateBase):
    id: Optional[int] = None
    entity_name: Optional[str] = None
    created: datetime

    class Config:
        from_attributes = True
        exclude_none = True


class ActionData(BaseModel):
    key: str
    value: int | str
