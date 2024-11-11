from pydantic_settings import BaseSettings, SettingsConfigDict
import platform


class Settings(BaseSettings):
    sqlalchemy_database_url: str = "sqlite:///./storage.db"
    questdb_configs: list[dict[str, str]] = [
        {"host": "phao.oudenijhuis.org", "port": "9000"},
        {"host": "192.168.1.110", "port": "9000"},
    ]
    questdb_user: str
    questdb_password: str

    state_monitor_sample_interval: int = 60  # seconds
    state_responsive_sample_interval: int = 10  # seconds
    state_storage_interval: int = 5  # minutes
    state_delete_interval: int = 60 * 60  # seconds

    questdb_upload_timeout: int = 5 * 60  # seconds
    questdb_upload_interval: int = 5 * 60  # seconds
    startup_delay: int = 5  # seconds
    questdb_startup_chunk_size: int = 100
    cache_retention: int = 5  # minutes

    state_delete_after_days: int = 7  # days

    hymer_serial_port: str = "/dev/serial0"
    hymer_serial_timeout: int = 10  # seconds
    hymer_serial_speed: int = 115200

    bthome_sensors: dict[str, str] = {
        "inside": "7C:C6:B6:61:E5:68",
        "outside": "7C:C6:B6:65:75:A1",
    }

    bthome_entities: dict[str, list[str]] = {
        "inside": ["battery", "temperature", "humidity"],
        "outside": ["battery", "temperature", "humidity"],
    }

    victron_sensors: dict[str, dict[str, str]] = {
        "SmartSolar": {
            "address": "cf:3b:a3:e5:58:79",
            "key": "c35bc9a772f02d904010bf8cd4bab7cf",
        },
        "SmartShunt": {
            "address": "fb:a2:b2:2e:12:55",
            "key": "c10a7be1241dd928a17a0bc61eec8f50",
        },
    }

    victron_entities: dict[str, list[str]] = {
        "SmartShunt": [
            "voltage",
            "current",
            "remaining_mins",
            "soc",
            "consumed_ah",
        ],
        "SmartSolar": [
            "battery_charging_current",
            "battery_voltage",
            "charge_state",
            "solar_power",
            "yield_today",
        ],
    }

    hymer_sensor: str = "camper"
    hymer_entities: list[str] = [
        "household_voltage",
        "starter_voltage",
        "mains_voltage",
        "household_state",
        "water_state",
        "waste_state",
        "pump_state",
    ]

    model_config = SettingsConfigDict(env_file=".env")


class DebugSettings(Settings):
    hymer_serial_port: str = "/dev/pts/5"


class ProductionSettings(Settings):
    pass


if platform.machine() == "x86_64":
    settings = DebugSettings()
else:
    settings = ProductionSettings()
