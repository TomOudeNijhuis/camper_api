import dataclasses


@dataclasses.dataclass
class MeasTypes:
    state_name: str = None
    unit: str = None
    data_length: int = 1
    data_format: str = "unsigned_integer"
    factor: float = 1


MEAS_TYPES: dict[int, MeasTypes] = {
    0x00: MeasTypes(state_name="packet_id", unit="None"),
    0x01: MeasTypes(state_name="battery", unit="%"),
    0x2E: MeasTypes(state_name="humidity", unit="%"),
    0x3A: MeasTypes(state_name="button"),
    0x45: MeasTypes(
        state_name="temperature",
        unit="°C",
        data_length=2,
        data_format="signed_integer",
        factor=0.1,
    ),
}
