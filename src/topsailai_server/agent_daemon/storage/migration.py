'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-22
  Purpose: Auto-migration utility for database schema changes
  
  This module automatically detects and applies schema changes when the code
  model changes but the database already exists with an old schema.
'''

from typing import Dict, List, Set
from sqlalchemy import inspect, text, Index

from topsailai_server.agent_daemon import logger


class DatabaseMigrator:
    """Automatically migrate database schema when columns are added or changed."""
    
    def __init__(self, engine):
        self.engine = engine
        self._migrations_applied: Set[str] = set()
    
    def migrate(self):
        """Run all migrations to ensure database schema is up to date."""
        logger.info("Starting database schema migration check")
        
        # Get all table names from the database
        inspector = inspect(self.engine)
        existing_tables = set(inspector.get_table_names())
        
        logger.info("Existing tables: %s", list(existing_tables))
        
        # Migrate each table
        if 'session' in existing_tables:
            self._migrate_session_table()
        
        if 'message' in existing_tables:
            self._migrate_message_table()
        
        if self._migrations_applied:
            logger.info("Applied %d migration(s): %s", 
                       len(self._migrations_applied), 
                       list(self._migrations_applied))
        else:
            logger.info("No migrations needed - database schema is up to date")
    
    def _get_column_names(self, table_name: str) -> Set[str]:
        """Get all column names for a table."""
        inspector = inspect(self.engine)
        columns = inspector.get_columns(table_name)
        return {col['name'] for col in columns}
    
    def _get_index_names(self, table_name: str) -> Set[str]:
        """Get all index names for a table."""
        inspector = inspect(self.engine)
        indexes = inspector.get_indexes(table_name)
        return {idx['name'] for idx in indexes}
    
    def _add_column_if_not_exists(self, table_name: str, column_name: str, column_type: str):
        """Add a column to a table if it doesn't exist."""
        existing_columns = self._get_column_names(table_name)
        
        if column_name not in existing_columns:
            migration_key = f"{table_name}.{column_name}"
            if migration_key in self._migrations_applied:
                logger.debug("Migration '%s' already applied, skipping", migration_key)
                return
            
            logger.info("Adding missing column '%s' to table '%s'", column_name, table_name)
            
            with self.engine.connect() as conn:
                # SQLite syntax for adding columns
                sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                conn.execute(text(sql))
                conn.commit()
            
            # Verify the column was actually added
            new_columns = self._get_column_names(table_name)
            if column_name in new_columns:
                self._migrations_applied.add(migration_key)
                logger.info("Successfully added column '%s' to table '%s'", column_name, table_name)
            else:
                logger.error("Failed to add column '%s' to table '%s' - column not found after migration", 
                            column_name, table_name)
    
    def _create_index_if_not_exists(self, table_name: str, index_name: str, column_name: str):
        """Create an index on a column if it doesn't exist."""
        existing_indexes = self._get_index_names(table_name)
        
        if index_name not in existing_indexes:
            migration_key = f"idx_{table_name}.{index_name}"
            if migration_key in self._migrations_applied:
                logger.debug("Index migration '%s' already applied, skipping", migration_key)
                return
            
            logger.info("Creating missing index '%s' on table '%s' (column: %s)", 
                       index_name, table_name, column_name)
            
            with self.engine.connect() as conn:
                # Check if column exists before creating index
                existing_columns = self._get_column_names(table_name)
                if column_name in existing_columns:
                    sql = f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})"
                    conn.execute(text(sql))
                    conn.commit()
                    
                    # Verify the index was created
                    new_indexes = self._get_index_names(table_name)
                    if index_name in new_indexes:
                        self._migrations_applied.add(migration_key)
                        logger.info("Successfully created index '%s' on table '%s'", index_name, table_name)
                    else:
                        logger.error("Failed to create index '%s' on table '%s'", index_name, table_name)
                else:
                    logger.warning("Cannot create index '%s' - column '%s' does not exist", 
                                  index_name, column_name)
    
    def _migrate_session_table(self):
        """Migrate the session table to add any missing columns."""
        logger.info("Checking session table for schema updates")
        
        # Define expected columns and their types
        expected_columns = {
            'session_id': 'VARCHAR(32)',
            'session_name': 'VARCHAR(255)',
            'task': 'TEXT',
            'create_time': 'DATETIME',
            'update_time': 'DATETIME',
            'processed_msg_id': 'VARCHAR(32)',
        }
        
        # Add missing columns
        for col_name, col_type in expected_columns.items():
            self._add_column_if_not_exists('session', col_name, col_type)
        
        # Create missing indexes
        self._create_index_if_not_exists('session', 'ix_session_processed_msg_id', 'processed_msg_id')
    
    def _migrate_message_table(self):
        """Migrate the message table to add any missing columns."""
        logger.info("Checking message table for schema updates")
        
        # Define expected columns and their types
        expected_columns = {
            'msg_id': 'VARCHAR(32)',
            'session_id': 'VARCHAR(32)',
            'message': 'TEXT',
            'role': 'VARCHAR(32)',
            'create_time': 'DATETIME',
            'update_time': 'DATETIME',
            'task_id': 'VARCHAR(32)',
            'task_result': 'TEXT',
            'processed_msg_id': 'VARCHAR(32)',
        }
        
        # Add missing columns
        for col_name, col_type in expected_columns.items():
            self._add_column_if_not_exists('message', col_name, col_type)
        
        # Create missing indexes
        self._create_index_if_not_exists('message', 'ix_message_processed_msg_id', 'processed_msg_id')
        self._create_index_if_not_exists('message', 'ix_message_role', 'role')
        self._create_index_if_not_exists('message', 'ix_message_create_time', 'create_time')
        self._create_index_if_not_exists('message', 'ix_message_task_id', 'task_id')


def run_migrations(engine):
    """
    Run all database migrations.
    
    This should be called after creating the SQLAlchemy engine and before
    initializing the storage classes.
    
    Args:
        engine: SQLAlchemy engine instance
    """
    migrator = DatabaseMigrator(engine)
    migrator.migrate()
