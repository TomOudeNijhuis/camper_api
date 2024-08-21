from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    state_sample_interval: int = 60  # seconds


settings = Settings()
