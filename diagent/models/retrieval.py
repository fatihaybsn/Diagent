import uuid
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Retrieval(Base):
    __tablename__ = "retrievals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id"), nullable=False
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_chunks: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True
    )
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    source_age_hours: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
