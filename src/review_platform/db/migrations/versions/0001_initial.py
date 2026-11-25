"""Initial application schema."""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).parents[1].joinpath("schema.sql").read_text())


def downgrade() -> None:
    # Refuse any populated application table, including authentication and audit state.
    op.execute("""
    DO $$ DECLARE item record; populated boolean; BEGIN
      FOR item IN SELECT tablename FROM pg_tables
        WHERE schemaname = 'review_platform'
          AND tablename <> 'review_platform_alembic_version'
      LOOP
        EXECUTE format('SELECT EXISTS(SELECT 1 FROM review_platform.%I)', item.tablename)
          INTO populated;
        IF populated THEN
          RAISE EXCEPTION 'refusing to downgrade a populated review-platform database';
        END IF;
      END LOOP;
    END $$;
    """)
    op.execute("""
    DO $$ DECLARE item record; BEGIN
      FOR item IN SELECT tablename FROM pg_tables
        WHERE schemaname = 'review_platform'
          AND tablename <> 'review_platform_alembic_version'
      LOOP
        EXECUTE format('DROP TABLE review_platform.%I CASCADE', item.tablename);
      END LOOP;
      FOR item IN SELECT p.oid::regprocedure AS signature
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='review_platform'
      LOOP
        EXECUTE format('DROP FUNCTION %s CASCADE', item.signature);
      END LOOP;
      FOR item IN SELECT sequencename FROM pg_sequences WHERE schemaname='review_platform'
      LOOP
        EXECUTE format('DROP SEQUENCE review_platform.%I CASCADE', item.sequencename);
      END LOOP;
    END $$;
    """)
