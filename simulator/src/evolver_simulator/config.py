"""Configuracao validada do produtor de telemetria simulada."""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import Field, PositiveFloat, PositiveInt, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_VIALS = 16


class SimulatorSettings(BaseSettings):
    """Configuracao lida do ambiente e, opcionalmente, de ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    mqtt_host: str = Field(default="127.0.0.1", validation_alias="MQTT_HOST")
    mqtt_port: int = Field(default=1883, ge=1, le=65535, validation_alias="MQTT_PORT")
    mqtt_protocol_version: Literal[5] = Field(
        default=5,
        validation_alias="MQTT_PROTOCOL_VERSION",
    )
    mqtt_keepalive_seconds: PositiveInt = Field(
        default=60,
        validation_alias="MQTT_KEEPALIVE_SECONDS",
    )
    mqtt_connect_timeout_seconds: PositiveFloat = Field(
        default=10.0,
        validation_alias="MQTT_CONNECT_TIMEOUT_SECONDS",
    )
    mqtt_publish_timeout_seconds: PositiveFloat = Field(
        default=10.0,
        validation_alias="MQTT_PUBLISH_TIMEOUT_SECONDS",
    )
    mqtt_simulator_password: str = Field(
        min_length=1,
        validation_alias="MQTT_SIMULATOR_PASSWORD",
    )

    equipment_id: str = Field(
        default="evolver-sim-01",
        pattern=IDENTIFIER_PATTERN.pattern,
        validation_alias="SIMULATOR_EQUIPMENT_ID",
    )
    producer_id: str = Field(
        default="simulator-local-01",
        pattern=IDENTIFIER_PATTERN.pattern,
        validation_alias="SIMULATOR_PRODUCER_ID",
    )
    vial_ids_csv: str = Field(
        default="vial-01,vial-02,vial-03",
        validation_alias="SIMULATOR_VIAL_IDS",
    )
    interval_seconds: PositiveFloat = Field(
        default=2.0,
        validation_alias="SIMULATOR_INTERVAL_SECONDS",
    )
    seed: int = Field(default=2026, validation_alias="SIMULATOR_SEED")
    od_baseline: float = Field(
        default=0.35,
        ge=0.0,
        validation_alias="SIMULATOR_OD_BASELINE",
    )
    od_variation: float = Field(
        default=0.08,
        ge=0.0,
        validation_alias="SIMULATOR_OD_VARIATION",
    )
    od_noise: float = Field(
        default=0.005,
        ge=0.0,
        le=0.1,
        validation_alias="SIMULATOR_OD_NOISE",
    )
    max_messages: int | None = Field(
        default=None,
        gt=0,
        validation_alias="SIMULATOR_MAX_MESSAGES",
    )

    @field_validator("mqtt_host", "mqtt_simulator_password")
    @classmethod
    def non_blank_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @model_validator(mode="after")
    def validate_vials(self) -> Self:
        vial_ids = self.vial_ids
        if not vial_ids:
            raise ValueError("SIMULATOR_VIAL_IDS must contain at least one identifier")
        if len(vial_ids) > MAX_VIALS:
            raise ValueError(f"SIMULATOR_VIAL_IDS supports at most {MAX_VIALS} identifiers")
        if len(set(vial_ids)) != len(vial_ids):
            raise ValueError("SIMULATOR_VIAL_IDS must not contain duplicates")
        invalid = [vial_id for vial_id in vial_ids if not IDENTIFIER_PATTERN.fullmatch(vial_id)]
        if invalid:
            raise ValueError(f"invalid vial identifier: {invalid[0]}")
        return self

    @property
    def vial_ids(self) -> tuple[str, ...]:
        return tuple(part.strip() for part in self.vial_ids_csv.split(",") if part.strip())

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
