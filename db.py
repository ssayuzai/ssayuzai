r"""
데이터베이스(DB)예요. 회원 정보와 대화 기록을 파일 하나(data/ssayuz.db)에 저장해요.
SQLite는 Python에 기본으로 들어 있어서 따로 설치할 게 없어요.

표(테이블) 3개:
  users         : 회원 (아이디, 비밀번호를 알아볼 수 없게 바꾼 값)
  conversations : 대화방 (누구의 대화인지, 제목)
  turns         : 질문 하나와 그 답 (검색 기록)
"""

import datetime
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# 데이터를 저장하는 폴더. 시험할 때는 SSAYUZ_DATA_DIR 로 다른 폴더를 쓸 수 있어요
DATA_DIR = Path(os.environ.get("SSAYUZ_DATA_DIR", Path(__file__).parent / "data"))
DB_PATH = DATA_DIR / "ssayuz.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,  -- 대소문자가 달라도 같은 아이디로 봐요
    password_hash TEXT    NOT NULL,                        -- 비밀번호 원래 글자는 저장하지 않아요
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, updated_at);

CREATE TABLE IF NOT EXISTS turns (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    question        TEXT    NOT NULL,              -- 사용자가 쓴 질문
    understood      TEXT    NOT NULL,              -- 이전 대화를 보고 이해한 질문
    answer          TEXT    NOT NULL,              -- AI 정리 (실패했으면 오류 메시지)
    quick           TEXT,                          -- 빠른 답 (JSON)
    sources         TEXT    NOT NULL DEFAULT '[]', -- 출처 목록 (JSON)
    cited           TEXT    NOT NULL DEFAULT '[]', -- 답에 쓰인 출처 번호 (JSON)
    dropped         INTEGER NOT NULL DEFAULT 0,    -- 근거가 없어서 뺀 문장 수
    seconds         REAL,                          -- 걸린 시간
    ok              INTEGER NOT NULL DEFAULT 1,    -- 1 = 성공, 0 = 오류
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_conversation ON turns(conversation_id, id);
"""


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


@contextmanager
def connect():
    """DB를 열고, 일이 끝나면 저장하고 닫아요."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row  # 결과를 row["이름"] 처럼 꺼낼 수 있게 해요
    conn.execute("PRAGMA foreign_keys = ON")  # 회원을 지우면 그 사람의 대화도 함께 지워져요
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    """처음 실행할 때 폴더와 표를 만들어요. 이미 있으면 그대로 둬요."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")  # 읽기와 쓰기가 서로 덜 기다리게 해요
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# 회원
# ---------------------------------------------------------------------------

def create_user(username: str, password_hash: str) -> int | None:
    """회원을 만들고 번호를 돌려줘요. 이미 있는 아이디면 None 을 돌려줘요."""
    try:
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, password_hash, _now()),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def find_user(username: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_user(user_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


# ---------------------------------------------------------------------------
# 대화방
# ---------------------------------------------------------------------------

def create_conversation(user_id: int, title: str) -> int:
    now = _now()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, title, now, now),
        )
        return cur.lastrowid


def list_conversations(user_id: int) -> list[dict]:
    """이 회원의 대화방 목록 (최근에 쓴 것부터)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, title, updated_at FROM conversations WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def owns_conversation(user_id: int, conversation_id: int) -> bool:
    """이 대화방이 이 회원 것인지 확인해요. 남의 대화는 볼 수 없어야 해요."""
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id)
        ).fetchone()
    return row is not None


def delete_conversation(user_id: int, conversation_id: int) -> bool:
    """대화방과 그 안의 기록을 지워요. 지웠으면 True."""
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id)
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# 질문과 답 (검색 기록)
# ---------------------------------------------------------------------------

def _turn_to_dict(row: sqlite3.Row) -> dict:
    turn = dict(row)
    turn["quick"] = json.loads(turn["quick"]) if turn["quick"] else None
    turn["sources"] = json.loads(turn["sources"])
    turn["cited"] = json.loads(turn["cited"])
    turn["ok"] = bool(turn["ok"])
    return turn


def get_turns(conversation_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM turns WHERE conversation_id = ? ORDER BY id", (conversation_id,)
        ).fetchall()
    return [_turn_to_dict(r) for r in rows]


def recent_history(conversation_id: int, limit: int = 2) -> list[dict]:
    """이어지는 질문을 이해할 때 쓸 최근 대화 (성공한 것만, 오래된 것부터)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT understood, answer FROM turns WHERE conversation_id = ? AND ok = 1 "
            "ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
    # 이전 질문은 '이해한 질문'을 써요. "그럼 토성은?" 보다 "토성의 위성은 몇 개야?"가 뜻이 분명해요
    return [{"question": r["understood"], "answer": r["answer"]} for r in reversed(rows)]


def add_turn(conversation_id: int, question: str, understood: str, answer: str, *,
             quick: dict | None = None, result: dict | None = None,
             seconds: float | None = None, ok: bool = True) -> int:
    """질문과 답을 저장하고, 대화방의 '최근 사용 시각'을 바꿔요."""
    result = result or {}
    now = _now()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO turns (conversation_id, question, understood, answer, quick, sources, cited, "
            "dropped, seconds, ok, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id, question, understood, answer,
                json.dumps(quick, ensure_ascii=False) if quick else None,
                json.dumps(result.get("sources", []), ensure_ascii=False),
                json.dumps(result.get("cited", [])),
                len(result.get("dropped", [])),
                round(seconds, 1) if seconds is not None else None,
                int(ok), now,
            ),
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        return cur.lastrowid
