from pydantic import BaseModel
from datetime import datetime


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
        orm_mode = True


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
        orm_mode = True


class State(BaseModel):
    id: int
    state: str
    created: datetime

    class Config:
        orm_mode = True
