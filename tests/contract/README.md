# Frozen contract fixtures

Everything in this folder is **frozen**. These files were written by theoricum 0.1.0 and describe
what users have on disk and in their backups:

- `bank/`: question packs in the native `theoricum/1` format (TOML and JSON, with and without a
  pack `id`, with and without question ids). The Anki deck is built by the test itself
  (`tests/anki_builder.py`), because `.apkg` files are git-ignored.
- `export-v1/`: `manifest.json` and `history.json` of a `dgt export` zip
  (`theoricum-export/1`, `theoricum-history/1`).

`tests/test_contract.py` checks that they still import with the same keys, content, history,
flags and saved questions, and that a new export still writes every v1 field.

Never edit these files to make a test pass. If a format really has to change, add a new format
version next to the old one (e.g. `export-v2/`), keep reading the old one, and write a migration.
