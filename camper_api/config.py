from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    state_sample_interval: int = 60  # seconds
    state_delete_interval: int = 60 * 60  # seconds

    state_delete_after_days: int = 10  # days

    interface_serial_port: str = "/dev/ttyUSB1"
    interface_serial_timeout: int = 3
    interface_serial_speed: int = 19200


settings = Settings()
