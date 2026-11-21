"""Migrations must apply cleanly, undo cleanly, and match the models exactly."""

from sqlalchemy import create_engine, inspect, make_url
from sqlalchemy.pool import NullPool

from alembic import command
from tests.conftest import alembic_config, recreate_database


def test_migrations_upgrade_downgrade_and_match_models(database_url: str) -> None:
    url = make_url(database_url)
    scratch_url = url.set(database=f"{url.database}_migrations").render_as_string(
        hide_password=False
    )
    recreate_database(scratch_url)
    config = alembic_config(scratch_url)

    command.upgrade(config, "head")
    # Fails if a model changed without a migration ("autogenerate would add something").
    command.check(config)

    command.downgrade(config, "base")
    engine = create_engine(scratch_url, poolclass=NullPool)
    with engine.connect() as connection:
        assert inspect(connection).get_table_names() == ["alembic_version"]
    engine.dispose()

    command.upgrade(config, "head")
