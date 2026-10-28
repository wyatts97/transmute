from core import get_settings, migrate_table_columns
from .encode_metadata import EncodeMetadataMixin
from .file_db import FileDB


class ConversionDB(EncodeMetadataMixin, FileDB):
    """Database class for managing converted file metadata.

    Extends FileDB to store metadata for files that are the result of
    a conversion operation. Uses a separate table from FileDB but shares
    the same schema and interface, with an additional quality column.

    Attributes:
        settings: Application settings instance.
        DB_PATH: Path to the SQLite database file.
        _TABLE_NAME: Name of the database table for conversion file metadata.
    """

    settings = get_settings()
    DB_PATH = settings.db_path
    _TABLE_NAME = settings.conversion_table_name

    def __init__(self) -> None:
        """Initialize ConversionDB and create the conversions table."""
        super().__init__()
        self._ensure_quality_column()
        self._ensure_encode_columns()

    def _ensure_quality_column(self) -> None:
        """Ensure the conversion metadata table has the optional quality column."""
        migrate_table_columns(self.conn, self.TABLE_NAME, {
            "quality": "TEXT",
        })

    def create_tables(self) -> None:
        """Create the conversion metadata table with the quality column."""
        super().create_tables()
        self._ensure_quality_column()
        self._ensure_encode_columns()

    def insert_file_metadata(self, metadata: dict) -> None:
        """Insert a new conversion file metadata record, including optional quality."""
        quality = metadata.pop('quality', None)
        options, preset, encoder_used = self._pop_encode_metadata(metadata)
        super().insert_file_metadata(metadata)
        self._store_encode_metadata(metadata['id'], options, preset, encoder_used)
        if quality is not None:
            with self.conn:
                self.conn.execute(
                    f"UPDATE {self.TABLE_NAME} SET quality = ? WHERE id = ?",  # nosec B608
                    (quality, metadata['id']),
                )
