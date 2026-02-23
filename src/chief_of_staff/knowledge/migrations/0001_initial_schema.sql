CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,          -- 'gmail', 'gdocs', 'elevenlabs', 'meeting'
    source_id TEXT NOT NULL,       -- external ID from the source system
    title TEXT,
    content_preview TEXT,          -- first ~500 chars
    metadata TEXT,                 -- JSON blob for source-specific data
    ingested_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source, source_id)
);

CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    practice_name TEXT,
    email TEXT,
    phone TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    founder_phone TEXT NOT NULL,
    direction TEXT NOT NULL,       -- 'inbound' or 'outbound'
    message TEXT NOT NULL,
    response TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'in_progress', 'completed', 'failed'
    result TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS email_conversations (
    id TEXT PRIMARY KEY,
    email_address TEXT NOT NULL,
    thread_id TEXT,
    gmail_message_id TEXT UNIQUE,
    rfc_message_id TEXT,
    direction TEXT NOT NULL,
    subject TEXT,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_email_conv_thread ON email_conversations(thread_id);
CREATE INDEX IF NOT EXISTS idx_email_conv_addr ON email_conversations(email_address);
CREATE INDEX IF NOT EXISTS idx_email_conv_created ON email_conversations(created_at);

CREATE TABLE IF NOT EXISTS processed_gmail_events (
    gmail_message_id TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS complaints (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    sender TEXT NOT NULL,
    thread_id TEXT,
    severity TEXT NOT NULL DEFAULT 'medium',
    summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduled_actions (
    id TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    schedule_time TEXT NOT NULL,
    channel TEXT NOT NULL,
    target TEXT DEFAULT '',
    prompt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    last_run_at TEXT,
    next_run_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sub_agent_runs (
    id TEXT PRIMARY KEY,
    parent_agent TEXT NOT NULL,
    child_agent TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',  -- queued, running, completed, failed, cancelled
    result TEXT DEFAULT '',
    error TEXT DEFAULT '',
    requester_channel TEXT DEFAULT '',
    requester_user_id TEXT DEFAULT '',
    requester_session_id TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT DEFAULT '',
    ended_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sub_agent_runs_parent_created ON sub_agent_runs(parent_agent, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sub_agent_runs_status ON sub_agent_runs(status);
