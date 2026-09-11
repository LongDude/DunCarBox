import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_DATABASE_URL = "postgresql://duncarbox:duncarbox@127.0.0.1:5432/duncarbox"


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = field(repr=False)
    demo_dir: Path
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    def __post_init__(self) -> None:
        if urlsplit(self.database_url).scheme not in {"postgresql", "postgres"}:
            raise ValueError("DUNCARBOX_DATABASE_URL must be a PostgreSQL connection URI")

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(__file__).resolve().parents[1]
        return cls(
            database_url=os.getenv("DUNCARBOX_DATABASE_URL", DEFAULT_DATABASE_URL),
            demo_dir=Path(os.getenv("DUNCARBOX_DEMO_DIR", root.parent / "demo")),
            cors_origins=tuple(
                origin.strip()
                for origin in os.getenv(
                    "DUNCARBOX_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
                ).split(",")
                if origin.strip()
            ),
        )
