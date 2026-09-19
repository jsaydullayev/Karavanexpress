"""cargo_id prefix support + client agent link

Revision ID: cargo_id_prefix
Revises: add_grp_categories
Create Date: 2026-09-19

1. `clients.cargo_id` VARCHAR(5) -> VARCHAR(10).
   Alohida klient ID lari "MS48392" ko'rinishida (MS + 5 raqam = 7 belgi),
   eski ustunga sig'masdi. Mavjud 5 xonali ID lar o'zgarmaydi.

2. `clients.agent_id` ustuni — mijoz kim nomidan ro'yxatga olinganini
   ko'rsatadi (self-referential FK). NULL = oddiy mijoz.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'cargo_id_prefix'
down_revision: Union[str, None] = 'add_grp_categories'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'clients', 'cargo_id',
        existing_type=sa.VARCHAR(length=5),
        type_=sa.VARCHAR(length=10),
        existing_nullable=True,
    )

    op.add_column(
        'clients',
        sa.Column('agent_id', sa.BIGINT(), nullable=True),
    )
    op.create_index('ix_clients_agent_id', 'clients', ['agent_id'])
    op.create_foreign_key(
        'fk_clients_agent_id_clients',
        'clients', 'clients',
        ['agent_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_clients_agent_id_clients', 'clients', type_='foreignkey')
    op.drop_index('ix_clients_agent_id', table_name='clients')
    op.drop_column('clients', 'agent_id')

    # Prefiksli ID lar (MS48392) VARCHAR(5) ga sig'maydi. Ularni jimgina
    # o'chirib yuborish xavfli — avval tekshiramiz va ma'lumot yo'qoladigan
    # bo'lsa, downgrade'ni to'xtatamiz. Hech narsa o'zgarmaydi.
    conn = op.get_bind()
    prefixed = conn.execute(
        sa.text("SELECT count(*) FROM clients WHERE cargo_id ~ '[^0-9]'")
    ).scalar() or 0

    if prefixed:
        raise RuntimeError(
            f"{prefixed} ta mijozda prefiksli Cargo ID bor (masalan MS48392). "
            "Downgrade ularni yo'q qiladi. Avval shu ID larni qo'lda hal qiling "
            "(o'chiring yoki 5 xonali IDga o'tkazing), keyin qaytadan urinib ko'ring."
        )

    op.alter_column(
        'clients', 'cargo_id',
        existing_type=sa.VARCHAR(length=10),
        type_=sa.VARCHAR(length=5),
        existing_nullable=True,
    )
