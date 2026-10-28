import sqlite3
import threading
import uuid
from typing import Optional

from core import get_settings, validate_sql_identifier, migrate_table_columns

'''
Anywhere you see # nosec B608, it is marking a Bandit false positive. The table
name is validated and locked after initialization, and the values are
parameterized to prevent SQL injection.
'''


class PresetDB:
    """Database class for user-defined encode presets.

    Each row stores a named ``EncodeOptions`` payload (as JSON) owned by one
    user. Requests reference a preset by its ``id`` through the ``preset``
    field; built-in presets live in code (``encoding.presets``) and never
    touch this table.
    """

    settings = get_settings()
    DB_PATH = settings.db_path
    _TABLE_NAME = settings.presets_table_name

    _UPDATABLE = ("name", "description", "kind", "options_json")

    @property
    def TABLE_NAME(self) -> str:
        return self._table_name

    def __init__(self) -> None:
        object.__setattr__(self, '_table_name', validate_sql_identifier(self._TABLE_NAME))
        self._local = threading.local()
        self.create_tables()

    @property
    def conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.DB_PATH)
        return self._local.conn

    def create_tables(self) -> None:
        with self.conn:
            self.conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    kind TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)  # nosec B608

        migrate_table_columns(self.conn, self.TABLE_NAME, {
            "user_id":       "TEXT",
            "name":          "TEXT",
            "description":   "TEXT",
            "kind":          "TEXT",
            "options_json":  "TEXT",
            "created_at":    "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "updated_at":    "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        })

        with self.conn:
            self.conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.TABLE_NAME}_user "  # nosec B608
                f"ON {self.TABLE_NAME} (user_id, name)"
            )

    def _row(self, cursor: sqlite3.Cursor) -> Optional[dict]:
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_preset(self, preset_id: str, user_id: str) -> Optional[dict]:
        cursor = self.conn.cursor()
        cursor.row_factory = sqlite3.Row
        cursor.execute(
            f"SELECT * FROM {self.TABLE_NAME} WHERE id = ? AND user_id = ?",  # nosec B608
            (preset_id, user_id),
        )
        return self._row(cursor)

    def list_presets(self, user_id: str) -> list[dict]:
        cursor = self.conn.cursor()
        cursor.row_factory = sqlite3.Row
        cursor.execute(
            f"SELECT * FROM {self.TABLE_NAME} WHERE user_id = ? ORDER BY name COLLATE NOCASE, created_at",  # nosec B608
            (user_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def insert_preset(self, *, user_id: str, name: str, kind: str, options_json: str, description: str | None = None) -> dict:
        preset_id = str(uuid.uuid4())
        with self.conn:
            self.conn.execute(
                f"INSERT INTO {self.TABLE_NAME} (id, user_id, name, description, kind, options_json) "  # nosec B608
                f"VALUES (?, ?, ?, ?, ?, ?)",
                (preset_id, user_id, name, description, kind, options_json),
            )
        preset = self.get_preset(preset_id, user_id)
        if preset is None:
            raise RuntimeError(f"Preset {preset_id} not found immediately after insert")
        return preset

    def update_preset(self, preset_id: str, user_id: str, fields: dict) -> Optional[dict]:
        """Update the given columns; unknown keys are ignored. Returns the row or None."""
        updates = {k: v for k, v in fields.items() if k in self._UPDATABLE}
        if updates:
            assignments = ", ".join(f"{column} = ?" for column in updates)
            with self.conn:
                self.conn.execute(
                    f"UPDATE {self.TABLE_NAME} SET {assignments}, updated_at = CURRENT_TIMESTAMP "  # nosec B608
                    f"WHERE id = ? AND user_id = ?",
                    (*updates.values(), preset_id, user_id),
                )
        return self.get_preset(preset_id, user_id)

    def delete_preset(self, preset_id: str, user_id: str) -> bool:
        with self.conn:
            cursor = self.conn.execute(
                f"DELETE FROM {self.TABLE_NAME} WHERE id = ? AND user_id = ?",  # nosec B608
                (preset_id, user_id),
            )
            return cursor.rowcount > 0

    def delete_all_for_user(self, user_id: str) -> int:
        with self.conn:
            cursor = self.conn.execute(
                f"DELETE FROM {self.TABLE_NAME} WHERE user_id = ?",  # nosec B608
                (user_id,),
            )
            return cursor.rowcount

    def close(self) -> None:
        if hasattr(self._local, 'conn') and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None
