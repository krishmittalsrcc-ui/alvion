"""SQLite persistence. Multi-user from the start so seats can be sold later."""
import json
import sqlite3
import time
import uuid

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    pw_hash TEXT NOT NULL,
    pw_salt TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'local',
    credit_ceiling REAL,
    planner_model TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS credentials (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    enc BLOB NOT NULL,
    hint TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, provider)
);
CREATE TABLE IF NOT EXISTS brands (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    tagline TEXT,
    details TEXT,
    accent TEXT NOT NULL DEFAULT '#5b8cff',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS brand_assets (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    path TEXT,
    link TEXT,
    note TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    brand_id TEXT REFERENCES brands(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    note TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    state TEXT NOT NULL,
    params TEXT NOT NULL,
    brief TEXT,
    plan TEXT,
    estimate TEXT,
    credits_spent REAL NOT NULL DEFAULT 0,
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    clip_id TEXT,
    path TEXT,
    url TEXT,
    request_id TEXT,
    meta TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    ts REAL NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shots (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    clip_id TEXT NOT NULL,
    data TEXT NOT NULL,
    image_status TEXT NOT NULL DEFAULT 'pending',
    image_path TEXT, image_url TEXT, image_version INTEGER NOT NULL DEFAULT 0,
    image_feedback TEXT,
    clip_status TEXT NOT NULL DEFAULT 'pending',
    clip_path TEXT, clip_url TEXT, clip_version INTEGER NOT NULL DEFAULT 0,
    clip_feedback TEXT,
    qc TEXT, error TEXT,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shots_job ON shots(job_id, idx);
CREATE TABLE IF NOT EXISTS job_assets (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    path TEXT, link TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_brands_user ON brands(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bassets_brand ON brand_assets(brand_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, id);
CREATE INDEX IF NOT EXISTS idx_assets_job ON assets(job_id);
"""


def connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


MIGRATIONS = [
    ("jobs", "edit", "TEXT"),
    ("jobs", "render", "TEXT"),
    ("jobs", "stage_note", "TEXT"),
]


def init():
    conn = connect()
    with conn:
        conn.executescript(SCHEMA)
        for table, col, typ in MIGRATIONS:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)]
            if col not in cols:
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, typ))
    conn.close()


def nid():
    return uuid.uuid4().hex[:16]


def _js(v):
    return json.dumps(v) if v is not None else None


def _unjs(v):
    return json.loads(v) if v else None


# --- users -----------------------------------------------------------------

def create_user(email, pw_hash, pw_salt, is_admin=False):
    uid = nid()
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO users (id,email,pw_hash,pw_salt,plan,is_admin,created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (uid, email.lower().strip(), pw_hash, pw_salt, "local", int(is_admin), time.time()))
    conn.close()
    return uid


def get_user_by_email(email):
    conn = connect()
    r = conn.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
    conn.close()
    return dict(r) if r else None


def get_user(uid):
    conn = connect()
    r = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return dict(r) if r else None


def user_count():
    conn = connect()
    n = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    conn.close()
    return n


def update_user(uid, **fields):
    if not fields:
        return
    cols = ",".join("%s=?" % k for k in fields)
    conn = connect()
    with conn:
        conn.execute("UPDATE users SET %s WHERE id=?" % cols, list(fields.values()) + [uid])
    conn.close()


# --- sessions --------------------------------------------------------------

def create_session(user_id, token, days):
    now = time.time()
    conn = connect()
    with conn:
        conn.execute("INSERT INTO sessions (token,user_id,created_at,expires_at) VALUES (?,?,?,?)",
                     (token, user_id, now, now + days * 86400))
    conn.close()


def session_user(token):
    if not token:
        return None
    conn = connect()
    r = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id"
        " WHERE s.token=? AND s.expires_at > ?", (token, time.time())).fetchone()
    conn.close()
    return dict(r) if r else None


def delete_session(token):
    conn = connect()
    with conn:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.close()


# --- credentials -----------------------------------------------------------

def set_credential(user_id, provider, enc, hint):
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO credentials (user_id,provider,enc,hint,updated_at) VALUES (?,?,?,?,?)"
            " ON CONFLICT(user_id,provider) DO UPDATE SET enc=excluded.enc,"
            " hint=excluded.hint, updated_at=excluded.updated_at",
            (user_id, provider, enc, hint, time.time()))
    conn.close()


def get_credential(user_id, provider):
    conn = connect()
    r = conn.execute("SELECT * FROM credentials WHERE user_id=? AND provider=?",
                     (user_id, provider)).fetchone()
    conn.close()
    return dict(r) if r else None


def list_credentials(user_id):
    conn = connect()
    rows = conn.execute("SELECT provider,hint,updated_at FROM credentials WHERE user_id=?",
                        (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_credential(user_id, provider):
    conn = connect()
    with conn:
        conn.execute("DELETE FROM credentials WHERE user_id=? AND provider=?", (user_id, provider))
    conn.close()


# --- jobs ------------------------------------------------------------------

def create_job(user_id, title, params, project_id=None):
    jid = nid()
    now = time.time()
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO jobs (id,user_id,project_id,title,state,params,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (jid, user_id, project_id, title, "draft", _js(params), now, now))
    conn.close()
    return jid


def get_job(job_id, user_id=None):
    conn = connect()
    if user_id:
        r = conn.execute("SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)).fetchone()
    else:
        r = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not r:
        return None
    j = dict(r)
    for k in ("params", "brief", "plan", "estimate", "edit", "render"):
        j[k] = _unjs(j.get(k))
    return j


JOB_COLS = ("SELECT j.id,j.title,j.state,j.credits_spent,j.error,j.created_at,"
            "j.updated_at,j.project_id,p.name AS project_name,p.brand_id,"
            "b.name AS brand_name,b.accent,"
            "(SELECT a.id FROM assets a WHERE a.job_id=j.id AND a.kind='frame' "
            " ORDER BY a.created_at LIMIT 1) AS thumb_id,"
            "(SELECT a.id FROM assets a WHERE a.job_id=j.id AND a.kind='final' "
            " ORDER BY a.created_at DESC LIMIT 1) AS final_id "
            "FROM jobs j LEFT JOIN projects p ON p.id=j.project_id "
            "LEFT JOIN brands b ON b.id=p.brand_id ")


def list_jobs(user_id, limit=100, project_id=None):
    conn = connect()
    if project_id:
        rows = conn.execute(JOB_COLS + "WHERE j.user_id=? AND j.project_id=?"
                            " ORDER BY j.created_at DESC LIMIT ?",
                            (user_id, project_id, limit)).fetchall()
    else:
        rows = conn.execute(JOB_COLS + "WHERE j.user_id=? ORDER BY j.created_at DESC LIMIT ?",
                            (user_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_job(job_id, **fields):
    if not fields:
        return
    for k in ("params", "brief", "plan", "estimate", "edit", "render"):
        if k in fields:
            fields[k] = _js(fields[k])
    fields["updated_at"] = time.time()
    cols = ",".join("%s=?" % k for k in fields)
    conn = connect()
    with conn:
        conn.execute("UPDATE jobs SET %s WHERE id=?" % cols, list(fields.values()) + [job_id])
    conn.close()


def add_credits(job_id, amount):
    conn = connect()
    with conn:
        conn.execute("UPDATE jobs SET credits_spent=credits_spent+?, updated_at=? WHERE id=?",
                     (amount, time.time(), job_id))
    conn.close()


def user_credits_spent(user_id):
    conn = connect()
    r = conn.execute("SELECT COALESCE(SUM(credits_spent),0) s FROM jobs WHERE user_id=?",
                     (user_id,)).fetchone()
    conn.close()
    return float(r["s"])


# --- assets / events -------------------------------------------------------

def add_asset(job_id, kind, path=None, url=None, clip_id=None, request_id=None, meta=None):
    aid = nid()
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO assets (id,job_id,kind,clip_id,path,url,request_id,meta,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (aid, job_id, kind, clip_id, path, url, request_id, _js(meta), time.time()))
    conn.close()
    return aid


def list_assets(job_id, kind=None):
    conn = connect()
    if kind:
        rows = conn.execute("SELECT * FROM assets WHERE job_id=? AND kind=? ORDER BY created_at",
                            (job_id, kind)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM assets WHERE job_id=? ORDER BY created_at",
                            (job_id,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["meta"] = _unjs(d["meta"])
        out.append(d)
    return out


def log(job_id, message, level="info"):
    conn = connect()
    with conn:
        conn.execute("INSERT INTO events (job_id,ts,level,message) VALUES (?,?,?,?)",
                     (job_id, time.time(), level, message))
    conn.close()


def events_since(job_id, after_id=0, limit=300):
    conn = connect()
    rows = conn.execute(
        "SELECT id,ts,level,message FROM events WHERE job_id=? AND id>? ORDER BY id LIMIT ?",
        (job_id, after_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- brands ----------------------------------------------------------------

def create_brand(user_id, name, tagline=None, details=None, accent="#5b8cff"):
    bid = nid()
    conn = connect()
    with conn:
        conn.execute("INSERT INTO brands (id,user_id,name,tagline,details,accent,created_at)"
                     " VALUES (?,?,?,?,?,?,?)",
                     (bid, user_id, name, tagline, details, accent, time.time()))
    conn.close()
    return bid


def list_brands(user_id):
    conn = connect()
    rows = conn.execute(
        "SELECT b.*, (SELECT COUNT(*) FROM projects p WHERE p.brand_id=b.id) AS project_count,"
        " (SELECT COUNT(*) FROM brand_assets a WHERE a.brand_id=b.id) AS asset_count"
        " FROM brands b WHERE b.user_id=? ORDER BY b.created_at DESC", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_brand(brand_id, user_id):
    conn = connect()
    r = conn.execute("SELECT * FROM brands WHERE id=? AND user_id=?", (brand_id, user_id)).fetchone()
    conn.close()
    return dict(r) if r else None


def update_brand(brand_id, user_id, **fields):
    if not fields:
        return
    cols = ",".join("%s=?" % k for k in fields)
    conn = connect()
    with conn:
        conn.execute("UPDATE brands SET %s WHERE id=? AND user_id=?" % cols,
                     list(fields.values()) + [brand_id, user_id])
    conn.close()


def delete_brand(brand_id, user_id):
    conn = connect()
    with conn:
        conn.execute("DELETE FROM brands WHERE id=? AND user_id=?", (brand_id, user_id))
    conn.close()


# --- brand assets ----------------------------------------------------------

def add_brand_asset(brand_id, user_id, kind, name, path=None, link=None, note=None):
    aid = nid()
    conn = connect()
    with conn:
        conn.execute("INSERT INTO brand_assets (id,brand_id,user_id,kind,name,path,link,note,"
                     "created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (aid, brand_id, user_id, kind, name, path, link, note, time.time()))
    conn.close()
    return aid


def list_brand_assets(brand_id, user_id):
    conn = connect()
    rows = conn.execute("SELECT * FROM brand_assets WHERE brand_id=? AND user_id=?"
                        " ORDER BY created_at DESC", (brand_id, user_id)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_brand_asset(asset_id, user_id):
    conn = connect()
    r = conn.execute("SELECT * FROM brand_assets WHERE id=? AND user_id=?",
                     (asset_id, user_id)).fetchone()
    conn.close()
    return dict(r) if r else None


def delete_brand_asset(asset_id, user_id):
    conn = connect()
    with conn:
        conn.execute("DELETE FROM brand_assets WHERE id=? AND user_id=?", (asset_id, user_id))
    conn.close()


# --- projects --------------------------------------------------------------

def create_project(user_id, name, brand_id=None, note=None):
    pid = nid()
    conn = connect()
    with conn:
        conn.execute("INSERT INTO projects (id,user_id,brand_id,name,note,created_at)"
                     " VALUES (?,?,?,?,?,?)", (pid, user_id, brand_id, name, note, time.time()))
    conn.close()
    return pid


def list_projects(user_id, brand_id=None):
    conn = connect()
    q = ("SELECT p.*, b.name AS brand_name, b.accent,"
         " (SELECT COUNT(*) FROM jobs j WHERE j.project_id=p.id) AS video_count"
         " FROM projects p LEFT JOIN brands b ON b.id=p.brand_id WHERE p.user_id=?")
    args = [user_id]
    if brand_id:
        q += " AND p.brand_id=?"
        args.append(brand_id)
    rows = conn.execute(q + " ORDER BY p.created_at DESC", args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_project(project_id, user_id):
    conn = connect()
    r = conn.execute("SELECT p.*, b.name AS brand_name, b.accent, b.details AS brand_details"
                     " FROM projects p LEFT JOIN brands b ON b.id=p.brand_id"
                     " WHERE p.id=? AND p.user_id=?", (project_id, user_id)).fetchone()
    conn.close()
    return dict(r) if r else None


def delete_project(project_id, user_id):
    conn = connect()
    with conn:
        conn.execute("DELETE FROM projects WHERE id=? AND user_id=?", (project_id, user_id))
    conn.close()


# --- shots (one per clip in the plan) ---------------------------------------

def replace_shots(job_id, clips):
    now = time.time()
    conn = connect()
    with conn:
        conn.execute("DELETE FROM shots WHERE job_id=?", (job_id,))
        for i, c in enumerate(clips):
            conn.execute("INSERT INTO shots (id,job_id,idx,clip_id,data,updated_at)"
                         " VALUES (?,?,?,?,?,?)", (nid(), job_id, i, c.get("id") or "C%d" % (i + 1),
                                                   _js(c), now))
    conn.close()


def _shot(r):
    d = dict(r)
    d["data"] = _unjs(d["data"]) or {}
    d["qc"] = _unjs(d["qc"])
    return d


def list_shots(job_id):
    conn = connect()
    rows = conn.execute("SELECT * FROM shots WHERE job_id=? ORDER BY idx", (job_id,)).fetchall()
    conn.close()
    return [_shot(r) for r in rows]


def get_shot(shot_id, job_id=None):
    conn = connect()
    if job_id:
        r = conn.execute("SELECT * FROM shots WHERE id=? AND job_id=?", (shot_id, job_id)).fetchone()
    else:
        r = conn.execute("SELECT * FROM shots WHERE id=?", (shot_id,)).fetchone()
    conn.close()
    return _shot(r) if r else None


def update_shot(shot_id, **fields):
    for k in ("data", "qc"):
        if k in fields:
            fields[k] = _js(fields[k])
    fields["updated_at"] = time.time()
    cols = ",".join("%s=?" % k for k in fields)
    conn = connect()
    with conn:
        conn.execute("UPDATE shots SET %s WHERE id=?" % cols, list(fields.values()) + [shot_id])
    conn.close()


# --- per-video uploads and links ------------------------------------------

def add_job_asset(job_id, kind, name, path=None, link=None):
    aid = nid()
    conn = connect()
    with conn:
        conn.execute("INSERT INTO job_assets (id,job_id,kind,name,path,link,created_at)"
                     " VALUES (?,?,?,?,?,?,?)", (aid, job_id, kind, name, path, link, time.time()))
    conn.close()
    return aid


def list_job_assets(job_id):
    conn = connect()
    rows = conn.execute("SELECT * FROM job_assets WHERE job_id=? ORDER BY created_at",
                        (job_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
