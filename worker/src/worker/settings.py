"""Worker settings — delegasi ke CoreSettings agar satu sumber konfigurasi."""

from ai_asistent_core.config import CoreSettings
from ai_asistent_core.config import get_settings as core_settings


class WorkerSettings(CoreSettings):
    """Konfigurasi worker (mewarisi semua env APP_*)."""


def get_settings() -> CoreSettings:
    """Alias ke core settings (cache)."""
    return core_settings()
