-- Schema version 1.
--
-- Content cache: rebuilt from questions/ at any time by the library sync.
CREATE TABLE sources (
    id             INTEGER PRIMARY KEY,
    path           TEXT NOT NULL UNIQUE,          -- relative to the questions folder (posix)
    kind           TEXT NOT NULL,                 -- native | apkg | crowdanki
    fingerprint    TEXT NOT NULL,
    name           TEXT,
    origin         TEXT NOT NULL DEFAULT 'otro',
    priority       INTEGER NOT NULL DEFAULT 0,
    enabled        INTEGER NOT NULL DEFAULT 1,
    exclude_topics TEXT NOT NULL DEFAULT '[]',    -- JSON array of topic slugs
    n_questions    INTEGER NOT NULL DEFAULT 0,
    warnings       TEXT NOT NULL DEFAULT '[]',    -- JSON array of messages
    error          TEXT,
    synced_at      TEXT NOT NULL
);

CREATE TABLE questions (
    source_id   INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,                    -- stable identity, referenced by user data
    text        TEXT NOT NULL,
    options     TEXT NOT NULL,                    -- JSON array of strings
    answer      INTEGER NOT NULL,                 -- index into options
    explanation TEXT,
    image_ref   TEXT,                             -- "file:<path>" | "apkg:<path>!<member>"
    topic       TEXT NOT NULL,
    date        TEXT,
    tags        TEXT NOT NULL DEFAULT '[]',
    source      TEXT,
    dedup       TEXT NOT NULL,
    PRIMARY KEY (source_id, key)
);
CREATE INDEX idx_questions_key ON questions (key);
CREATE INDEX idx_questions_dedup ON questions (dedup);
CREATE INDEX idx_questions_topic ON questions (topic);

-- User data: never touched by the sync. References questions by key (no FK on purpose).
CREATE TABLE sessions (
    id           INTEGER PRIMARY KEY,
    uuid         TEXT NOT NULL UNIQUE,
    mode         TEXT NOT NULL,                   -- exam | study | review | topic
    topic        TEXT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    time_limit_s INTEGER,
    elapsed_s    REAL,
    n_questions  INTEGER NOT NULL,
    n_correct    INTEGER,
    n_wrong      INTEGER,
    n_blank      INTEGER,
    passed       INTEGER,
    status       TEXT NOT NULL DEFAULT 'in_progress'   -- in_progress | finished | abandoned
);

CREATE TABLE answers (
    session_id   INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    question_key TEXT NOT NULL,
    chosen       INTEGER,                          -- NULL = not answered
    is_correct   INTEGER,
    answered_at  TEXT,
    PRIMARY KEY (session_id, position)
);
CREATE INDEX idx_answers_key ON answers (question_key);

CREATE TABLE flags (
    question_key TEXT PRIMARY KEY,
    disabled     INTEGER NOT NULL DEFAULT 0,
    flagged      INTEGER NOT NULL DEFAULT 0,
    note         TEXT,
    updated_at   TEXT NOT NULL
);
