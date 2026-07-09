from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    APP_NAME: str = (
        "IDMS DB2 Modernizer"
    )

    BASE_DIR: Path = Path.cwd()

    INPUT_DIR: str = "data/input"

    OUTPUT_DIR: str = "data/output"

    TEMP_DIR: str = "data/temp"

    DEBUG: bool = True

    @property
    def input_dir(self) -> str:
        return self.INPUT_DIR

    @property
    def output_dir(self) -> str:
        return self.OUTPUT_DIR

    @property
    def temp_dir(self) -> str:
        return self.TEMP_DIR

    class Config:
        env_file = ".env"


settings = Settings()