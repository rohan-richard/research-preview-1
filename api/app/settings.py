from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://rumi:rumi@localhost:5432/rumi"
    jwt_secret: str = Field(min_length=32)
    google_client_ids: str = ""
    apple_client_ids: str = ""
    cors_origins: str = ""
    chat_server_url: str = ""
    chat_server_api_key: str = ""
    chat_server_visit_prep_api_key: str = ""
    s3_bucket: str = ""
    # Without S3_BUCKET, export files go here and this API serves them. Relative paths start at the api folder.
    local_files_dir: str = "var/files"
    api_base_url: str = "http://localhost:8000"
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_private_key: str = ""
    apns_bundle_id: str = ""
    apns_use_sandbox: bool = False
    chat_server_webhook_secret: str = ""
    fasten_public_id: str = ""
    fasten_private_key: str = ""
    fasten_webhook_secret: str = ""
    fasten_api_url: str = "https://api.connect.fastenhealth.com/v1"
    # Local development only. Never turn this on in a deployed environment.
    dev_sign_in: bool = False

    @staticmethod
    def _split(value: str) -> list[str]:
        return [part.strip() for part in value.split(",") if part.strip()]

    @property
    def google_audiences(self) -> list[str]:
        return self._split(self.google_client_ids)

    @property
    def apple_audiences(self) -> list[str]:
        return self._split(self.apple_client_ids)

    @property
    def cors_origin_list(self) -> list[str]:
        return self._split(self.cors_origins)


settings = Settings()
