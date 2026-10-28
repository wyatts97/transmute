import json

from core import migrate_table_columns


class EncodeMetadataMixin:
    """Advanced-encoding columns shared by the conversion and compression result tables.

    Stores the resolved ``options`` (as JSON), the named ``preset`` they came
    from, and the ``encoder_used`` for each produced file, and decodes
    ``options_json`` back into an ``options`` dict on read. Mix in before
    ``FileDB``.
    """

    _ENCODE_COLUMNS = {
        "options_json": "TEXT",
        "preset": "TEXT",
        "encoder_used": "TEXT",
    }

    def _ensure_encode_columns(self) -> None:
        migrate_table_columns(self.conn, self.TABLE_NAME, self._ENCODE_COLUMNS)

    @staticmethod
    def _pop_encode_metadata(metadata: dict) -> tuple:
        return (
            metadata.pop("options", None),
            metadata.pop("preset", None),
            metadata.pop("encoder_used", None),
        )

    def _store_encode_metadata(self, file_id: str, options, preset, encoder_used) -> None:
        if options is None and preset is None and encoder_used is None:
            return
        options_json = json.dumps(options, sort_keys=True) if options is not None else None
        with self.conn:
            self.conn.execute(
                f"UPDATE {self.TABLE_NAME} SET options_json = ?, preset = ?, encoder_used = ? WHERE id = ?",  # nosec B608
                (options_json, preset, encoder_used, file_id),
            )

    @staticmethod
    def decode_encode_metadata(row: dict) -> dict:
        raw = row.pop("options_json", None)
        try:
            row["options"] = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            row["options"] = None
        return row

    def get_file_metadata(self, file_id: str):
        row = super().get_file_metadata(file_id)
        return self.decode_encode_metadata(row) if row else row

    def list_files(self, user_id: str | None = None) -> list[dict]:
        return [self.decode_encode_metadata(row) for row in super().list_files(user_id)]
