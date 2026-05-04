from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongodb_uri: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_database: str = Field(default="initiative", alias="MONGODB_DATABASE")
    mongodb_username: str = Field(default="", alias="MONGODB_USERNAME")
    mongodb_password: str = Field(default="", alias="MONGODB_PASSWORD")
    mongodb_auth_source: str = Field(default="admin", alias="MONGODB_AUTH_SOURCE")
    discord_token: str = Field(default="", alias="DISCORD_TOKEN")
    discord_command_prefix: str = Field(default="!", alias="DISCORD_COMMAND_PREFIX")
    discord_registration_emoji: str = Field(
        default="Initiative_blason",
        alias="DISCORD_REGISTRATION_EMOJI",
    )
    registration_url: str = Field(
        default="https://initiative-kourial.fr",
        alias="REGISTRATION_URL",
    )
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def mongodb_connection_uri(self) -> str:
        if not self.mongodb_username or not self.mongodb_password:
            return self.mongodb_uri

        username = quote_plus(self.mongodb_username)
        password = quote_plus(self.mongodb_password)
        base_uri = self.mongodb_uri.removeprefix("mongodb://").removeprefix("mongodb+srv://")
        protocol = "mongodb+srv" if self.mongodb_uri.startswith("mongodb+srv://") else "mongodb"

        return f"{protocol}://{username}:{password}@{base_uri}/?authSource={self.mongodb_auth_source}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
