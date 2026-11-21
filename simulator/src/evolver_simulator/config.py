"""Configuracao validada do produtor de telemetria simulada."""

from __future__ import annotations

from typing import Self

from pydantic import Field, PositiveFloat, PositiveInt, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"


class SimulatorSettings(BaseSettings):
    """Configuracao lida do ambiente e, opcionalmente, de ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    # Conexão com o broker MQTT.
    mqtt_host: str = Field(default="127.0.0.1", validation_alias="MQTT_HOST")
    mqtt_port: int = Field(default=1883, ge=1, le=65535, validation_alias="MQTT_PORT")
    mqtt_protocol_version: int = Field(
        default=5, ge=5, le=5, validation_alias="MQTT_PROTOCOL_VERSION"
    )
    mqtt_keepalive_seconds: PositiveInt = Field(
        default=60, validation_alias="MQTT_KEEPALIVE_SECONDS"
    )
    mqtt_connect_timeout_seconds: PositiveFloat = Field(
        default=10.0, validation_alias="MQTT_CONNECT_TIMEOUT_SECONDS"
    )
    mqtt_publish_timeout_seconds: PositiveFloat = Field(
        default=10.0, validation_alias="MQTT_PUBLISH_TIMEOUT_SECONDS"
    )
    mqtt_simulator_password: str = Field(min_length=1, validation_alias="MQTT_SIMULATOR_PASSWORD")

    # Identidade, frascos e ritmo das medições.
    equipment_id: str = Field(
        default="evolver-sim-01",
        pattern=IDENTIFIER_PATTERN,
        validation_alias="SIMULATOR_EQUIPMENT_ID",
    )
    producer_id: str = Field(
        default="simulator-local-01",
        pattern=IDENTIFIER_PATTERN,
        validation_alias="SIMULATOR_PRODUCER_ID",
    )
    seed: int | None = Field(default=None, validation_alias="SIMULATOR_SEED")

    # Valores simulados: base, tamanho da onda e ruído de cada medição.
    od_baseline: float = Field(default=0.35, ge=0.0, validation_alias="SIMULATOR_OD_BASELINE")
    od_variation: float = Field(default=0.08, ge=0.0, validation_alias="SIMULATOR_OD_VARIATION")
    od_noise: float = Field(default=0.005, ge=0.0, le=0.1, validation_alias="SIMULATOR_OD_NOISE")
    ph_baseline: float = Field(default=7.0, validation_alias="SIMULATOR_PH_BASELINE")
    ph_variation: float = Field(default=0.15, ge=0.0, validation_alias="SIMULATOR_PH_VARIATION")
    ph_noise: float = Field(default=0.02, ge=0.0, validation_alias="SIMULATOR_PH_NOISE")
    temperature_baseline: float = Field(
        default=37.0, validation_alias="SIMULATOR_TEMPERATURE_BASELINE"
    )
    temperature_variation: float = Field(
        default=0.5, ge=0.0, validation_alias="SIMULATOR_TEMPERATURE_VARIATION"
    )
    temperature_noise: float = Field(
        default=0.1, ge=0.0, validation_alias="SIMULATOR_TEMPERATURE_NOISE"
    )

    # Limite e cenários opcionais para testes.
    max_messages: int | None = Field(default=None, gt=0, validation_alias="SIMULATOR_MAX_MESSAGES")
    pause_after_messages: int | None = Field(
        default=None, gt=0, validation_alias="SIMULATOR_PAUSE_AFTER_MESSAGES"
    )
    pause_seconds: float | None = Field(
        default=None, gt=0, validation_alias="SIMULATOR_PAUSE_SECONDS"
    )
    fail_after_messages: int | None = Field(
        default=None, gt=0, validation_alias="SIMULATOR_FAIL_AFTER_MESSAGES"
    )

    @field_validator("mqtt_host", "mqtt_simulator_password")
    @classmethod
    def non_blank_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @model_validator(mode="after")
    def validate_simulated_scenario(self) -> Self:
        pause_is_partial = (self.pause_after_messages is None) != (self.pause_seconds is None)
        if pause_is_partial:
            raise ValueError(
                "SIMULATOR_PAUSE_AFTER_MESSAGES and SIMULATOR_PAUSE_SECONDS "
                "must be configured together",
            )
        if self.pause_after_messages is not None and self.fail_after_messages is not None:
            raise ValueError("configure either a pause scenario or a failure scenario, not both")
        return self

    @property
    def mqtt_username(self) -> str:
        """A ACL local usa o ``equipment_id`` como usuario MQTT."""

        return self.equipment_id

    @property
    def mqtt_client_id(self) -> str:
        return f"{self.producer_id}-telemetry"

    @property
    def telemetry_topic(self) -> str:
        return f"evolver/v1/{self.equipment_id}/telemetry"
