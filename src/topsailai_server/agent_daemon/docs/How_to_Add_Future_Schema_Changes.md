---
maintainer: AI
---

# How to Add Future Schema Changes

This document explains how to add new columns or indexes to the agent_daemon database schema using the built-in auto-migration system.

## 1. Overview

The auto-migration system (`storage/migration.py`) automatically detects and applies schema changes when the code model changes but the database already exists with an old schema. This eliminates the need to manually delete `.db` files during development or handle schema drift in production.

**Key capabilities:**
- Detects missing columns using SQLAlchemy's `inspect()`
- Adds missing columns using `ALTER TABLE ADD COLUMN`
- Creates missing indexes
- Verifies migrations succeeded
- Works with SQLite (and other SQLAlchemy-supported databases)

## 2. How It Works

### Trigger Points

The migration runs automatically at two places:

1. **In `main.py`** — After engine creation, before storage initialization:
   ```python
   from topsailai_server.agent_daemon.storage.migration import run_migrations
   
   engine = create_engine(db_url)
   run_migrations(engine)  # <-- Auto-migration happens here
   storage = Storage(engine)
   ```

2. **In `storage/__init__.py`** — Inside the `Storage` class initialization:
   ```python
   def __init__(self, engine):
       from topsailai_server.agent_daemon.storage.migration import run_migrations
       run_migrations(engine)
       # ... rest of initialization
   ```

### Detection Mechanism

The `DatabaseMigrator` class uses SQLAlchemy's `inspect()` to:
- Get existing table names
- Get existing column names per table
- Get existing index names per table

### Migration Process

For each table (e.g., `message`, `session`):

1. **Check existing columns** — Compare against expected columns defined in migration config
2. **Add missing columns** — Execute `ALTER TABLE <name> ADD COLUMN <col> <type>`
3. **Create missing indexes** — Execute `CREATE INDEX IF NOT EXISTS <idx> ON <table> (<col>)`
4. **Verify** — Re-inspect to confirm changes were applied
5. **Log** — Report what migrations were applied

### What It Does NOT Do

- ❌ Does NOT drop columns
- ❌ Does NOT modify existing column types
- ❌ Does NOT remove indexes
- ❌ Does NOT migrate data (only schema changes)

## 3. Step-by-Step: Adding a New Column

### Example: Adding a `priority` field to the `message` table

#### Step 1: Update the SQLAlchemy Model

**File:** `storage/message_manager/sql.py`

```python
class Message(Base):
    __tablename__ = 'message'
    
    msg_id = Column(String(32), primary_key=True)
    session_id = Column(String(32), nullable=False)
    # ... existing columns ...
    task_result = Column(Text, nullable=True)
    processed_msg_id = Column(String(32), nullable=True)
    
    # ADD THIS NEW COLUMN
    priority = Column(String(16), nullable=True)  # e.g., 'high', 'normal', 'low'
```

#### Step 2: Update the Dataclass

**File:** `storage/message_manager/base.py`

```python
@dataclass
class MessageData:
    msg_id: str
    session_id: str
    role: str
    message: str
    create_time: datetime
    update_time: datetime
    # ... existing fields ...
    task_id: Optional[str] = None
    task_result: Optional[str] = None
    processed_msg_id: Optional[str] = None
    
    # ADD THIS NEW FIELD
    priority: Optional[str] = None  # default=None for backward compatibility
```

#### Step 3: Update the Migration Configuration

**File:** `storage/migration.py`

Find the `_migrate_message_table` method and add the new column:

```python
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
        
        # ADD THE NEW COLUMN HERE
        'priority': 'VARCHAR(16)',  # <-- Add this line
    }
    
    # Add missing columns
    for col_name, col_type in expected_columns.items():
        self._add_column_if_not_exists('message', col_name, col_type)
    
    # Create missing indexes
    self._create_index_if_not_exists('message', 'ix_message_processed_msg_id', 'processed_msg_id')
    self._create_index_if_not_exists('message', 'ix_message_role', 'role')
    self._create_index_if_not_exists('message', 'ix_message_create_time', 'create_time')
    self._create_index_if_not_exists('message', 'ix_message_task_id', 'task_id')
    
    # ADD INDEX FOR NEW COLUMN (if needed)
    self._create_index_if_not_exists('message', 'ix_message_priority', 'priority')  # <-- Optional
```

#### Step 4: Update API Routes and Storage Methods

If the new field needs to be accepted via API or stored/retrieved:

**File:** `api/routes/message.py`
```python
class ReceiveMessageRequest(BaseModel):
    message: str
    session_id: str
    role: str = "user"
    processed_msg_id: Optional[str] = None
    
    # ADD THIS
    priority: Optional[str] = None  # <-- Add field
```

**File:** `storage/message_manager/sql.py` (in `create()` method)
```python
def create(self, data: MessageData) -> MessageData:
    # ... existing code ...
    
    # ADD THIS LINE
    if data.priority is not None:
        msg.priority = data.priority
    
    # ... rest of code ...
```

#### Step 5: Restart the Service

```bash
# Restart the daemon
./topsailai_agent_daemon.py stop
./topsailai_agent_daemon.py start

# Or run tests - migration happens automatically
pytest tests/unit/ -v
```

Check the logs for migration output:
```
INFO - Starting database schema migration check
INFO - Existing tables: ['message', 'session']
INFO - Adding missing column 'priority' to table 'message'
INFO - Successfully added column 'priority' to table 'message'
INFO - Applied 1 migration(s): ['message.priority']
```

## 4. Migration Configuration Reference

### Structure

```python
MIGRATION_CONFIG = {
    "table_name": {
        "columns": {
            "column_name": "SQLITE_TYPE",
            # ...
        },
        "indexes": {
            "index_name": ["column_name"],
            # ...
        }
    }
}
```

### Current Configuration

#### Session Table (`_migrate_session_table`)

| Column | Type | Index |
|--------|------|-------|
| session_id | VARCHAR(32) | — |
| session_name | VARCHAR(255) | — |
| task | TEXT | — |
| create_time | DATETIME | — |
| update_time | DATETIME | — |
| processed_msg_id | VARCHAR(32) | ix_session_processed_msg_id |

#### Message Table (`_migrate_message_table`)

| Column | Type | Index |
|--------|------|-------|
| msg_id | VARCHAR(32) | — |
| session_id | VARCHAR(32) | — |
| message | TEXT | — |
| role | VARCHAR(32) | ix_message_role |
| create_time | DATETIME | ix_message_create_time |
| update_time | DATETIME | — |
| task_id | VARCHAR(32) | ix_message_task_id |
| task_result | TEXT | — |
| processed_msg_id | VARCHAR(32) | ix_message_processed_msg_id |

### SQLite Type Reference

| Python Type | SQLite Type | Notes |
|-------------|-------------|-------|
| str (short) | VARCHAR(32) | For IDs, roles |
| str (long) | TEXT | For message content |
| datetime | DATETIME | ISO format timestamps |
| int | INTEGER | — |
| float | REAL | — |
| bool | INTEGER | 0 or 1 |

## 5. Important Notes / Best Practices

### SQLite Limitations

SQLite's `ALTER TABLE` has significant limitations:

1. **Cannot drop columns** — SQLite does not support `ALTER TABLE DROP COLUMN`. To remove a column, you must recreate the table.
2. **Cannot add NOT NULL columns** — New columns must be nullable or have a DEFAULT value.
3. **Cannot rename columns** — Column renaming requires table recreation.
4. **Cannot change column types** — Type changes require table recreation.

**Recommendation:** Always add new columns as nullable without a default for backward compatibility.

### Best Practices

1. **Always use nullable columns** — Set `nullable=True` and no default value:
   ```python
   new_field = Column(String(32), nullable=True)  # ✅ Good
   new_field = Column(String(32), nullable=False)  # ❌ Bad - may fail on existing rows
   ```

2. **Use VARCHAR for IDs, TEXT for content** — Keep IDs short (32-64 chars) for index efficiency.

3. **Add indexes for frequently queried columns** — But don't over-index; each index slows writes.

4. **Test migration on a copy of production data** — Especially for large tables, verify migration time is acceptable.

5. **Keep migration config in sync with model** — The migration config should match the SQLAlchemy model definition.

6. **Document breaking changes** — If you need to drop/modify a column, document it as a breaking change requiring manual migration.

### What the Migration System Handles

| Change Type | Supported? | Notes |
|-------------|------------|-------|
| Add new nullable column | ✅ Yes | Primary use case |
| Add new index | ✅ Yes | Full support |
| Drop column | ❌ No | Requires manual migration |
| Change column type | ❌ No | Requires manual migration |
| Rename column | ❌ No | Add new, migrate data, drop old |

## 6. Troubleshooting

### Migration Fails with "table X has no column Y"

**Cause:** The migration was interrupted or the SQLite file is corrupted.

**Solution:**
```bash
# Check the current schema
sqlite3 your_database.db ".schema message"

# If corrupted, delete and let SQLAlchemy recreate (development only!)
rm your_database.db
# Restart the service - SQLAlchemy will create fresh tables
```

### Column Exists But Migration Says It Doesn't

**Cause:** Cached migration state or case-sensitivity issue.

**Solution:**
```bash
# Verify column exists (SQLite is case-insensitive but check anyway)
sqlite3 your_database.db "PRAGMA table_info(message);"
```

### Index Creation Fails

**Cause:** Column doesn't exist yet when index is created.

**Solution:** The migration code checks for column existence before creating indexes. If this fails, ensure the column migration runs before the index migration (current implementation does this correctly).

### "no such table" Error

**Cause:** Database file doesn't exist or is empty.

**Solution:** SQLAlchemy will create tables automatically on first use. No migration needed.

### As a Last Resort (Development Only)

```bash
# Delete the database file and let SQLAlchemy recreate it
rm /path/to/your/database.db
# Restart the service
```

**Warning:** This deletes ALL data. Only use in development or when data loss is acceptable.

### Checking Migration Logs

The migration system logs to:
- Console (stdout/stderr)
- Log file: `/topsailai/log/agent_daemon.log`

Look for these log entries:
```
INFO - Starting database schema migration check
INFO - Existing tables: [...]
INFO - Adding missing column 'X' to table 'Y'
INFO - Successfully added column 'X' to table 'Y'
INFO - Applied N migration(s): [...]
INFO - No migrations needed - database schema is up to date
```

## 7. Adding a New Table

To add an entirely new table:

1. Create the SQLAlchemy model in the appropriate module
2. Add a migration method in `storage/migration.py`:
   ```python
   def _migrate_new_table(self):
       inspector = inspect(self.engine)
       existing_tables = set(inspector.get_table_names())
       
       if 'new_table' not in existing_tables:
           logger.info("Creating new table 'new_table'")
           # Create table using SQLAlchemy metadata
           Base.metadata.create_all(self.engine)
   ```
3. Call the new method in `migrate()`:
   ```python
   if 'new_table' in existing_tables:
       self._migrate_new_table()
   ```

Note: For new tables, SQLAlchemy's `Base.metadata.create_all()` is usually sufficient since the table doesn't exist yet.
