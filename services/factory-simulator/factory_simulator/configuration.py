from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    ingestion_host: str
    ingestion_port: int

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "Settings":
        host = environment.get("INGESTION_TCP_HOST", "").strip()
        raw_port = environment.get("INGESTION_TCP_PORT", "").strip()
        if not host:
            raise ValueError("INGESTION_TCP_HOST is required")
        try:
            port = int(raw_port)
        except ValueError:
            raise ValueError("INGESTION_TCP_PORT must be an integer from 1 to 65535") from None
        if not 1 <= port <= 65535:
            raise ValueError("INGESTION_TCP_PORT must be an integer from 1 to 65535")
        return cls(host, port)
