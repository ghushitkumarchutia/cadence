from __future__ import annotations

from app.infrastructure import close_connections as _close
from app.infrastructure import get_db_pool

get_pool = get_db_pool
close_pool = _close
