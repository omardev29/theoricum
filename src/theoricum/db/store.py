"""SQLite access: connection setup, the content cache, user history and flags."""

import json
import sqlite3
import uuid as uuidlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from theoricum.db.migrations import migrate
from theoricum.models import AnswerEvent, ExamRecord, Flag, PackMeta, Question

HISTORY_FORMAT = "theoricum-history/1"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class QuestionRow:
    """A fully resolved question, ready to be stored in the content cache."""

    key: str
    text: str
    options: tuple[str, ...]
    answer: int
    explanation: str | None
    image_ref: str | None
    topic: str
    date: str | None
    tags: tuple[str, ...]
    source: str | None
    dedup: str


@dataclass(frozen=True, slots=True)
class SourceInfo:
    path: str
    kind: str
    fingerprint: str
    name: str | None
    origin: str
    priority: int
    enabled: bool
    n_questions: int
    warnings: tuple[str, ...]
    error: str | None
    synced_at: str


@dataclass(frozen=True, slots=True)
class HistoryImport:
    sessions: int = 0
    answers: int = 0
    flags: int = 0
    saved: int = 0


def _row_to_question(r: sqlite3.Row) -> Question:
    return Question(
        key=r["key"],
        text=r["text"],
        options=tuple(json.loads(r["options"])),
        answer=r["answer"],
        topic=r["topic"],
        origin=r["origin"],
        dedup=r["dedup"],
        priority=r["priority"],
        explanation=r["explanation"],
        image_ref=r["image_ref"],
        date=r["date"],
        source=r["source"],
        source_name=r["source_name"],
        tags=tuple(json.loads(r["tags"])),
    )


class Store:
    """Thin wrapper over one SQLite connection. Use one Store per thread."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @classmethod
    def open(cls, db_path: Path | str) -> Store:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if str(db_path) != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        migrate(conn)
        return cls(conn)

    def close(self) -> None:
        self.conn.close()

    # --- content cache ------------------------------------------------------------------------

    def source_fingerprints(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT path, fingerprint FROM sources")
        return {row["path"]: row["fingerprint"] for row in rows}

    def replace_source(
        self,
        *,
        path: str,
        kind: str,
        fingerprint: str,
        meta: PackMeta,
        rows: Sequence[QuestionRow],
        warnings: Sequence[str],
        error: str | None = None,
    ) -> None:
        """Atomically replace everything known about one source file."""
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO sources (path, kind, fingerprint, name, origin, priority, enabled,
                                     exclude_topics, n_questions, warnings, error, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (path) DO UPDATE SET
                    kind = excluded.kind, fingerprint = excluded.fingerprint,
                    name = excluded.name, origin = excluded.origin, priority = excluded.priority,
                    enabled = excluded.enabled, exclude_topics = excluded.exclude_topics,
                    n_questions = excluded.n_questions, warnings = excluded.warnings,
                    error = excluded.error, synced_at = excluded.synced_at
                RETURNING id
                """,
                (
                    path,
                    kind,
                    fingerprint,
                    meta.name,
                    meta.origin,
                    meta.effective_priority,
                    int(meta.enabled),
                    json.dumps(list(meta.exclude_topics)),
                    len(rows),
                    json.dumps(list(warnings), ensure_ascii=False),
                    error,
                    now_iso(),
                ),
            )
            source_id = cur.fetchone()[0]
            self.conn.execute("DELETE FROM questions WHERE source_id = ?", (source_id,))
            self.conn.executemany(
                """
                INSERT INTO questions (source_id, key, text, options, answer, explanation,
                                       image_ref, topic, date, tags, source, dedup)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        source_id,
                        r.key,
                        r.text,
                        json.dumps(list(r.options), ensure_ascii=False),
                        r.answer,
                        r.explanation,
                        r.image_ref,
                        r.topic,
                        r.date,
                        json.dumps(list(r.tags), ensure_ascii=False),
                        r.source,
                        r.dedup,
                    )
                    for r in rows
                ],
            )

    def delete_sources(self, paths: Iterable[str]) -> None:
        with self.conn:
            self.conn.executemany("DELETE FROM sources WHERE path = ?", [(p,) for p in paths])

    def sources(self) -> list[SourceInfo]:
        rows = self.conn.execute("SELECT * FROM sources ORDER BY path")
        return [
            SourceInfo(
                path=r["path"],
                kind=r["kind"],
                fingerprint=r["fingerprint"],
                name=r["name"],
                origin=r["origin"],
                priority=r["priority"],
                enabled=bool(r["enabled"]),
                n_questions=r["n_questions"],
                warnings=tuple(json.loads(r["warnings"])),
                error=r["error"],
                synced_at=r["synced_at"],
            )
            for r in rows
        ]

    def load_questions(self, *, since: str | None = None) -> list[Question]:
        """Active question pool: enabled sources, not disabled by the user, deduplicated."""
        disabled = {k for k, f in self.flags().items() if f.disabled}
        rows = self.conn.execute(
            """
            SELECT q.*, s.priority, s.origin, s.name AS source_name, s.exclude_topics
            FROM questions q JOIN sources s ON s.id = q.source_id
            WHERE s.enabled = 1
            """
        )
        best: dict[str, Question] = {}
        for r in rows:
            if r["key"] in disabled:
                continue
            if r["topic"] in json.loads(r["exclude_topics"]):
                continue
            if since and r["date"] and r["date"] < since:
                continue
            question = _row_to_question(r)
            current = best.get(question.dedup)
            if current is None or (-question.priority, question.key) < (
                -current.priority,
                current.key,
            ):
                best[question.dedup] = question
        return sorted(best.values(), key=lambda q: q.key)

    def questions_by_key(self, keys: Iterable[str]) -> dict[str, Question]:
        """Look questions up by key in any source (the highest priority one wins)."""
        keys = list(dict.fromkeys(keys))
        found: dict[str, Question] = {}
        for start in range(0, len(keys), 500):
            chunk = keys[start : start + 500]
            rows = self.conn.execute(
                f"""
                SELECT q.*, s.priority, s.origin, s.name AS source_name
                FROM questions q JOIN sources s ON s.id = q.source_id
                WHERE q.key IN ({", ".join("?" for _ in chunk)})
                """,
                chunk,
            )
            for r in rows:
                question = _row_to_question(r)
                current = found.get(question.key)
                if current is None or question.priority > current.priority:
                    found[question.key] = question
        return found

    def question_index(self) -> tuple[dict[str, str], dict[str, str]]:
        """For every cached question key: its duplicate group and its topic."""
        group_of: dict[str, str] = {}
        topic_of: dict[str, str] = {}
        for key, dedup, topic in self.conn.execute("SELECT key, dedup, topic FROM questions"):
            group_of[key] = dedup
            topic_of[key] = topic
        return group_of, topic_of

    # --- sessions -----------------------------------------------------------------------------

    def start_session(
        self,
        *,
        mode: str,
        keys: Sequence[str],
        topic: str | None = None,
        time_limit_s: int | None = None,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO sessions (uuid, mode, topic, started_at, time_limit_s, n_questions)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(uuidlib.uuid4()), mode, topic, now_iso(), time_limit_s, len(keys)),
            )
            session_id = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO answers (session_id, position, question_key) VALUES (?, ?, ?)",
                [(session_id, i, key) for i, key in enumerate(keys)],
            )
        assert session_id is not None
        return session_id

    def record_answer(
        self, session_id: int, position: int, chosen: int | None, is_correct: bool | None
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                UPDATE answers SET chosen = ?, is_correct = ?, answered_at = ?
                WHERE session_id = ? AND position = ?
                """,
                (
                    chosen,
                    None if is_correct is None else int(is_correct),
                    None if chosen is None else now_iso(),
                    session_id,
                    position,
                ),
            )

    def finish_session(
        self,
        session_id: int,
        *,
        n_correct: int,
        n_wrong: int,
        n_blank: int,
        passed: bool | None,
        elapsed_s: float | None,
        blanks_count_as_wrong: bool,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                UPDATE sessions SET status = 'finished', finished_at = ?, n_correct = ?, n_wrong = ?,
                       n_blank = ?, passed = ?, elapsed_s = ?
                WHERE id = ?
                """,
                (
                    now_iso(),
                    n_correct,
                    n_wrong,
                    n_blank,
                    None if passed is None else int(passed),
                    elapsed_s,
                    session_id,
                ),
            )
            if blanks_count_as_wrong:
                self.conn.execute(
                    "UPDATE answers SET is_correct = 0 WHERE session_id = ? AND chosen IS NULL",
                    (session_id,),
                )

    def abandon_session(self, session_id: int, elapsed_s: float | None = None) -> None:
        with self.conn:
            self.conn.execute(
                """
                UPDATE sessions SET status = 'abandoned', finished_at = ?, elapsed_s = ?
                WHERE id = ? AND status = 'in_progress'
                """,
                (now_iso(), elapsed_s, session_id),
            )

    def abandon_stale_sessions(self) -> int:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE sessions SET status = 'abandoned' WHERE status = 'in_progress'"
            )
        return cur.rowcount

    def answer_events(self) -> list[AnswerEvent]:
        rows = self.conn.execute(
            """
            SELECT a.question_key, a.is_correct, COALESCE(a.answered_at, s.finished_at, s.started_at) AS at
            FROM answers a JOIN sessions s ON s.id = a.session_id
            WHERE a.is_correct IS NOT NULL
            ORDER BY at, s.id, a.position
            """
        )
        return [AnswerEvent(r["question_key"], bool(r["is_correct"]), r["at"]) for r in rows]

    def exam_records(self) -> list[ExamRecord]:
        rows = self.conn.execute(
            """
            SELECT * FROM sessions WHERE mode = 'exam' AND status = 'finished' ORDER BY started_at, id
            """
        )
        return [
            ExamRecord(
                started_at=r["started_at"],
                n_questions=r["n_questions"],
                n_correct=r["n_correct"] or 0,
                n_wrong=r["n_wrong"] or 0,
                n_blank=r["n_blank"] or 0,
                passed=bool(r["passed"]),
                elapsed_s=r["elapsed_s"],
            )
            for r in rows
        ]

    def session_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE status = 'finished'"
        ).fetchone()[0]

    # --- flags --------------------------------------------------------------------------------

    def flags(self) -> dict[str, Flag]:
        rows = self.conn.execute("SELECT * FROM flags")
        return {
            r["question_key"]: Flag(
                bool(r["disabled"]), bool(r["flagged"]), r["note"], r["updated_at"]
            )
            for r in rows
        }

    def set_flag(
        self, key: str, *, disabled: bool | None = None, flagged: bool | None = None
    ) -> Flag:
        current = self.flags().get(key, Flag())
        new = Flag(
            disabled=current.disabled if disabled is None else disabled,
            flagged=current.flagged if flagged is None else flagged,
            note=current.note,
            updated_at=now_iso(),
        )
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO flags (question_key, disabled, flagged, note, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (question_key) DO UPDATE SET
                    disabled = excluded.disabled, flagged = excluded.flagged,
                    note = excluded.note, updated_at = excluded.updated_at
                """,
                (key, int(new.disabled), int(new.flagged), new.note, new.updated_at),
            )
        return new

    # --- saved questions --------------------------------------------------------------------

    def saved(self) -> dict[str, str]:
        """Saved question keys and when they were saved, most recent first."""
        rows = self.conn.execute("SELECT question_key, saved_at FROM saved ORDER BY saved_at DESC")
        return {r["question_key"]: r["saved_at"] for r in rows}

    def set_saved(self, key: str, saved: bool) -> None:
        with self.conn:
            if saved:
                self.conn.execute(
                    "INSERT OR IGNORE INTO saved (question_key, saved_at) VALUES (?, ?)",
                    (key, now_iso()),
                )
            else:
                self.conn.execute("DELETE FROM saved WHERE question_key = ?", (key,))

    # --- backup -------------------------------------------------------------------------------

    def export_history(self) -> dict[str, Any]:
        sessions = []
        for s in self.conn.execute(
            "SELECT * FROM sessions WHERE status != 'in_progress' ORDER BY id"
        ):
            answers = self.conn.execute(
                "SELECT * FROM answers WHERE session_id = ? ORDER BY position", (s["id"],)
            )
            sessions.append(
                {
                    **{k: v for k, v in dict(s).items() if k != "id"},
                    "answers": [
                        {k: v for k, v in dict(a).items() if k != "session_id"} for a in answers
                    ],
                }
            )
        flags = [dict(r) for r in self.conn.execute("SELECT * FROM flags ORDER BY question_key")]
        saved = [dict(r) for r in self.conn.execute("SELECT * FROM saved ORDER BY saved_at")]
        return {
            "format": HISTORY_FORMAT,
            "exported_at": now_iso(),
            "sessions": sessions,
            "flags": flags,
            "saved": saved,
        }

    def import_history(self, data: dict[str, Any]) -> HistoryImport:
        """Merge an exported history: sessions by uuid, flags by most recent `updated_at`."""
        if data.get("format") != HISTORY_FORMAT:
            raise ValueError(f"formato de historial no soportado: {data.get('format')!r}")
        n_sessions = n_answers = n_flags = 0
        session_cols = [
            "uuid", "mode", "topic", "started_at", "finished_at", "time_limit_s", "elapsed_s",
            "n_questions", "n_correct", "n_wrong", "n_blank", "passed", "status",
        ]  # fmt: skip
        answer_cols = ["position", "question_key", "chosen", "is_correct", "answered_at"]
        with self.conn:
            existing = {r[0] for r in self.conn.execute("SELECT uuid FROM sessions")}
            for s in data.get("sessions", []):
                if s["uuid"] in existing:
                    continue
                cur = self.conn.execute(
                    f"INSERT INTO sessions ({', '.join(session_cols)}) "
                    f"VALUES ({', '.join('?' for _ in session_cols)})",
                    [s.get(c) for c in session_cols],
                )
                answers = s.get("answers", [])
                self.conn.executemany(
                    f"INSERT INTO answers (session_id, {', '.join(answer_cols)}) "
                    f"VALUES (?, {', '.join('?' for _ in answer_cols)})",
                    [[cur.lastrowid, *(a.get(c) for c in answer_cols)] for a in answers],
                )
                existing.add(s["uuid"])
                n_sessions += 1
                n_answers += len(answers)
            current = self.flags()
            for f in data.get("flags", []):
                mine = current.get(f["question_key"])
                if mine and mine.updated_at and mine.updated_at >= f.get("updated_at", ""):
                    continue
                self.conn.execute(
                    """
                    INSERT INTO flags (question_key, disabled, flagged, note, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (question_key) DO UPDATE SET
                        disabled = excluded.disabled, flagged = excluded.flagged,
                        note = excluded.note, updated_at = excluded.updated_at
                    """,
                    (
                        f["question_key"],
                        f["disabled"],
                        f["flagged"],
                        f.get("note"),
                        f["updated_at"],
                    ),
                )
                n_flags += 1
            before = self.conn.total_changes
            self.conn.executemany(
                "INSERT OR IGNORE INTO saved (question_key, saved_at) VALUES (?, ?)",
                [(r["question_key"], r["saved_at"]) for r in data.get("saved", [])],
            )
            n_saved = self.conn.total_changes - before
        return HistoryImport(n_sessions, n_answers, n_flags, n_saved)
