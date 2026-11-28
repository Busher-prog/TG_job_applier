"""seed resume templates

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-25 18:36:58.706124
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql  # noqa: F401
from alembic import op


revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TEMPLATES = [
    {"code": "classic_ats", "name": "Classic ATS", "layout": "single_column", "ats_friendly": True, "sort_order": 1,
     "description": "Single-column, plain structure that applicant tracking systems read reliably.",
     "recommended_roles": ["Logistics", "Finance", "Engineering", "Administration", "Healthcare", "Public sector"]},
    {"code": "modern", "name": "Modern Professional", "layout": "single_column", "ats_friendly": True, "sort_order": 2,
     "description": "Single-column layout with a coloured header and accent headings.",
     "recommended_roles": ["Sales", "Marketing", "Project management", "Consulting", "IT"]},
    {"code": "creative", "name": "Creative", "layout": "two_column", "ats_friendly": False, "sort_order": 3,
     "description": "Bold header and a sidebar for contacts and skills; for creative roles.",
     "recommended_roles": ["Video editing", "Design", "Content creation", "Photography", "Social media"]},
]


def upgrade() -> None:
    table = sa.table(
        "resume_templates",
        sa.column("code", sa.String), sa.column("name", sa.String), sa.column("description", sa.Text),
        sa.column("layout", sa.String), sa.column("recommended_roles", sa.dialects.postgresql.JSONB),
        sa.column("ats_friendly", sa.Boolean), sa.column("is_active", sa.Boolean), sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(table, [{**t, "is_active": True} for t in TEMPLATES])


def downgrade() -> None:
    op.execute("DELETE FROM resume_templates WHERE code IN ('classic_ats', 'modern', 'creative')")
