from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    state_monitor_sample_interval: int = 60  # seconds
    state_responsive_sample_interval: int = 10  # seconds
    state_storage_interval: int = 5  # minutes
    state_delete_interval: int = 60 * 60  # seconds

    cache_retention: int = 5  # minutes

    state_delete_after_days: int = 7  # days

    interface_serial_port: str = "/dev/serial0"  # "/dev/pts/5"
    interface_serial_timeout: int = 3
    interface_serial_speed: int = 19200


settings = Settings()
