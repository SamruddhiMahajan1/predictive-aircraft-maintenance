"""FastAPI dependencies — db session and settings."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..db.session import get_db

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
