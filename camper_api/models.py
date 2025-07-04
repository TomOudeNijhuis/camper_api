from sqlalchemy import DateTime, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .database import Base


class Sensor(Base):
    __tablename__ = "sensors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, index=True)
    address = Column(String, nullable=True)
    key = Column(String, nullable=True)

    entities = relationship("Entity", cascade="all, delete-orphan")


class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id"))
    name = Column(String, index=True)
    unit = Column(String, nullable=True)
    description = Column(String, nullable=True)

    sensor = relationship("Sensor", viewonly=True)
    states = relationship("State", cascade="all, delete-orphan")


class State(Base):
    __tablename__ = "states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), index=True)
    state = Column(String(255))
    created = Column(DateTime, index=True)

    entity = relationship("Entity", viewonly=True)

    def row(self):
        return [
            self.created.isoformat(),
            self.entity.sensor.name,
            self.entity.name,
            self.state,
        ]


class Parameter(Base):
    __tablename__ = "parameters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, index=True)
    value = Column(String(255), nullable=True)
