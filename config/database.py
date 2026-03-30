"""
Database — pool de conexiones asyncpg hacia PostgreSQL multi-tenant.
"""
import logging
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def init_pool(database_url: str) -> None:
    """Inicializa el pool de conexiones. Llamar en el lifespan de FastAPI."""
    global _pool
    try:
        _pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info("[DB] Pool PostgreSQL inicializado correctamente.")
    except Exception as e:
        logger.error(f"[DB] Error inicializando pool: {e}")
        _pool = None


async def close_pool() -> None:
    """Cierra el pool. Llamar al apagar la app."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("[DB] Pool PostgreSQL cerrado.")


def get_pool() -> Optional[asyncpg.Pool]:
    """Retorna el pool activo o None si no está disponible."""
    return _pool
