"""One discover post per work."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_posts_work_unique"
down_revision = "0036_list_hot_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "posts" not in set(insp.get_table_names()):
        return

    op.execute(
        sa.text(
            """
            DELETE FROM posts
            WHERE id IN (
                SELECT id FROM (
                    SELECT older.id AS id
                    FROM posts AS older
                    WHERE EXISTS (
                        SELECT 1 FROM posts AS newer
                        WHERE newer.work_id = older.work_id
                          AND (
                            newer.created_at > older.created_at
                            OR (newer.created_at = older.created_at AND newer.id > older.id)
                          )
                    )
                ) stale
            )
            """
        )
    )

    existing = {idx["name"] for idx in insp.get_indexes("posts")}
    uniques = {uc["name"] for uc in insp.get_unique_constraints("posts")}
    if "uq_posts_work_id" not in existing and "uq_posts_work_id" not in uniques:
        op.create_index("uq_posts_work_id", "posts", ["work_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "posts" not in set(insp.get_table_names()):
        return
    existing = {idx["name"] for idx in insp.get_indexes("posts")}
    uniques = {uc["name"] for uc in insp.get_unique_constraints("posts")}
    if "uq_posts_work_id" in existing:
        op.drop_index("uq_posts_work_id", table_name="posts")
    elif "uq_posts_work_id" in uniques:
        op.drop_constraint("uq_posts_work_id", "posts", type_="unique")
