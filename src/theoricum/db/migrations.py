"""Schema migrations, tracked with `PRAGMA user_version`."""

import sqlite3
from importlib import resources


class SchemaTooNewError(Exception):
    """The database was created by a newer version of theoricum."""


def _migrations() -> list[str]:
    schema_v1 = resources.files("theoricum.db").joinpath("schema.sql").read_text(encoding="utf-8")
    # Append new migrations here; never edit an already released one.
    return [schema_v1]


def migrate(conn: sqlite3.Connection) -> None:
    migrations = _migrations()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > len(migrations):
        raise SchemaTooNewError(
            f"la base de datos es de una versión más nueva de theoricum (esquema {version})"
        )
    for number, script in enumerate(migrations[version:], start=version + 1):
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")
