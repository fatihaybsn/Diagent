"""Create initial tables.

Revision ID: 001
Revises: None
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── agents ──
    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(128), unique=True, nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ── runs ──
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("agents.id"),
            nullable=False,
        ),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ── spans ──
    op.create_table(
        "spans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=False
        ),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_spans_payload", "spans", ["payload"], postgresql_using="gin")

    # ── tool_calls ──
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=False
        ),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.create_index("ix_tool_calls_args", "tool_calls", ["args"], postgresql_using="gin")

    # ── retrievals ──
    op.create_table(
        "retrievals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=False
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("retrieved_chunks", postgresql.JSONB(), nullable=True),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("source_age_hours", sa.Numeric(10, 2), nullable=True),
    )
    op.create_index(
        "ix_retrievals_retrieved_chunks",
        "retrievals",
        ["retrieved_chunks"],
        postgresql_using="gin",
    )

    # ── evaluations ──
    op.create_table(
        "evaluations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=False
        ),
        sa.Column("faithfulness", sa.Numeric(4, 3), nullable=True),
        sa.Column("answer_relevancy", sa.Numeric(4, 3), nullable=True),
        sa.Column("context_precision", sa.Numeric(4, 3), nullable=True),
        sa.Column("overall_score", sa.Numeric(4, 3), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ── diagnoses ──
    op.create_table(
        "diagnoses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=False
        ),
        sa.Column("root_cause", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_diagnoses_evidence", "diagnoses", ["evidence"], postgresql_using="gin"
    )

    # ── alerts ──
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=True
        ),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index("ix_spans_run_id", "spans", ["run_id"])
    op.create_index("ix_tool_calls_run_id", "tool_calls", ["run_id"])
    op.create_index("ix_retrievals_run_id", "retrievals", ["run_id"])
    op.create_index("ix_evaluations_run_id", "evaluations", ["run_id"])
    op.create_index("ix_diagnoses_run_id", "diagnoses", ["run_id"])
    op.create_index("ix_alerts_run_id", "alerts", ["run_id"])



def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("diagnoses")
    op.drop_table("evaluations")
    op.drop_table("retrievals")
    op.drop_table("tool_calls")
    op.drop_table("spans")
    op.drop_table("runs")
    op.drop_table("agents")
