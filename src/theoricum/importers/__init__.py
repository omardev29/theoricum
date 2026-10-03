"""Question source adapters. Each one turns a file in questions/ into normalized questions."""

from theoricum.importers.base import ImportContext, Importer, ImportResult, PackError
from theoricum.importers.native import NativeImporter

# Bump when importer output changes, so cached sources are re-imported.
# 2: keys of packs without an id use `/` on Windows too.
IMPORTER_VERSION = 2


def default_importers() -> list[Importer]:
    from theoricum.importers.anki_json import CrowdAnkiImporter
    from theoricum.importers.apkg import ApkgImporter

    return [NativeImporter(), ApkgImporter(), CrowdAnkiImporter()]


__all__ = [
    "IMPORTER_VERSION",
    "ImportContext",
    "ImportResult",
    "Importer",
    "NativeImporter",
    "PackError",
    "default_importers",
]
