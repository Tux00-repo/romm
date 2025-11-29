"""
Unit tests for rom_notes table migration.
Test file: tests/test_migrations/test_rom_notes_migration.py
"""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.pool import NullPool
import os


@pytest.fixture(params=["postgresql", "mysql"])
def db_engine(request):
    """Create test database engines for different dialects."""
    dialect = request.param
    
    if dialect == "postgresql":
        database_url = os.getenv(
            "TEST_POSTGRES_URL",
            "postgresql://test_user:test_pass@localhost:5432/test_db"
        )
    else:  # mysql
        database_url = os.getenv(
            "TEST_MYSQL_URL",
            "mysql+pymysql://test_user:test_pass@localhost:3306/test_db"
        )
    
    engine = create_engine(database_url, poolclass=NullPool)
    yield engine, dialect
    engine.dispose()


@pytest.fixture
def alembic_config(db_engine):
    """Create Alembic configuration for testing."""
    engine, dialect = db_engine
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", str(engine.url))
    return config, engine, dialect


def test_upgrade_creates_table_and_indexes(alembic_config):
    """Test that upgrade creates rom_notes table with all indexes."""
    config, engine, dialect = alembic_config
    
    command.upgrade(config, "head")
    
    inspector = inspect(engine)
    
    # Verify table exists
    assert "rom_notes" in inspector.get_table_names()
    
    # Verify columns
    columns = {col["name"] for col in inspector.get_columns("rom_notes")}
    expected = {"id", "rom_id", "user_id", "title", "content", "is_public", "created_at", "updated_at"}
    assert expected.issubset(columns)
    
    # Verify indexes
    indexes = {idx["name"] for idx in inspector.get_indexes("rom_notes")}
    expected_indexes = {
        "idx_rom_notes_public",
        "idx_rom_notes_rom_user",
        "idx_rom_notes_title",
        "idx_rom_notes_content"
    }
    assert expected_indexes.issubset(indexes)


def test_downgrade_drops_table_and_restores_columns(alembic_config):
    """Test that downgrade removes rom_notes and restores rom_user columns."""
    config, engine, dialect = alembic_config
    
    # Upgrade then downgrade
    command.upgrade(config, "head")
    command.downgrade(config, "-1")
    
    inspector = inspect(engine)
    
    # Verify rom_notes is gone
    assert "rom_notes" not in inspector.get_table_names()
    
    # Verify rom_user columns are restored
    columns = {col["name"] for col in inspector.get_columns("rom_user")}
    assert "note_raw_markdown" in columns
    assert "note_is_public" in columns


def test_data_migration_roundtrip(alembic_config):
    """Test data migration from rom_user to rom_notes and back."""
    config, engine, dialect = alembic_config
    
    # Insert test data before upgrade
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO rom_user (id, rom_id, user_id, note_raw_markdown, note_is_public)
                VALUES (1, 100, 200, 'Test content', true)
            """)
        )
        conn.commit()
    
    # Upgrade - data should migrate to rom_notes
    command.upgrade(config, "head")
    
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT content, is_public FROM rom_notes WHERE rom_id = 100")
        ).fetchone()
        assert result.content == "Test content"
        assert result.is_public is True
    
    # Downgrade - data should migrate back
    command.downgrade(config, "-1")
    
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT note_raw_markdown, note_is_public FROM rom_user WHERE rom_id = 100")
        ).fetchone()
        assert result.note_raw_markdown == "Test content"
        assert result.note_is_public is True


def test_content_index_works_on_both_databases(alembic_config):
    """Test that content index is created successfully on both PostgreSQL and MySQL."""
    config, engine, dialect = alembic_config
    
    command.upgrade(config, "head")
    
    # Insert and query data to ensure index works
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO rom_notes (rom_id, user_id, title, content, is_public)
                VALUES (1, 1, 'Test', 'Searchable content here', true)
            """)
        )
        conn.commit()
        
        # Simple query that would use the content index
        result = conn.execute(
            text("SELECT * FROM rom_notes WHERE content LIKE '%Searchable%'")
        ).fetchone()
        
        assert result is not None
        assert "Searchable" in result.content
