r"""
브라우저에서 쓰는 ssayuz AI 웹 화면이에요. 회원가입, 로그인, 대화 기록 저장이 있어요.

실행: .venv\Scripts\python.exe app.py
      → 브라우저가 저절로 http://127.0.0.1:7860 을 열어요
      (브라우저를 열지 않으려면: app.py --no-browser)
끝내기: 이 창에서 Ctrl+C

인터넷 서버(Render)에서는 gunicorn 이 이 파일의 app 을 실행해요 (render.yaml 참고).
서버 설정은 환경 변수로 해요:
  SECRET_KEY          로그인 상태를 지키는 비밀 열쇠 (없으면 data/secret_key 파일에 만들어요)
  SSAYUZ_HTTPS=1      HTTPS 주소로 서비스할 때 켜요 (로그인 쿠키를 HTTPS로만 보내요)
"""

import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import traceback
import webbrowser
from datetime import timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory, session
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import brain
import db
from brain import BrainError
from main import run
from search import SearchError

# 내 컴퓨터에서만 접속할 수 있는 주소예요 (같은 와이파이의 다른 사람은 못 들어와요)
HOST = "127.0.0.1"
PORT = 7860
# 질문이 너무 길면 잘라요
MAX_QUESTION_CHARS = 300
# 화면 파일(index.html)이 있는 폴더
WEB_DIR = Path(__file__).parent / "web"
# 아이디: 한글, 영어, 숫자, _ 로 2~20글자
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_가-힣]{2,20}$")
# 비밀번호 길이
PASSWORD_MIN, PASSWORD_MAX = 8, 128
# 로그인을 이만큼 틀리면 잠시 막아요 (비밀번호를 마구 넣어 보는 공격 막기)
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_SECONDS = 300


def _secret_key() -> str:
    """로그인 상태(세션)를 지키는 비밀 열쇠예요.

    서버에서는 환경 변수 SECRET_KEY 를 써요 (Render 가 무작위로 만들어 줘요).
    없으면 처음 실행할 때 무작위로 만들어서 data/secret_key 에 저장해요.
    코드에 적어 두면 코드를 본 사람이 로그인 상태를 위조할 수 있어서 이렇게 해요.
    """
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = db.DATA_DIR / "secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    db.DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    path.write_text(key, encoding="utf-8")
    return key


# 윈도우는 .woff2(웹 글꼴) 파일 종류를 모를 때가 있어서 알려 줘요
mimetypes.add_type("font/woff2", ".woff2")

db.init()
app = Flask(__name__)
# HTTPS 주소로 서비스하는지 (Render 같은 인터넷 서버)
HTTPS = os.environ.get("SSAYUZ_HTTPS") == "1"
app.config.update(
    SECRET_KEY=_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,      # 페이지의 자바스크립트가 로그인 쿠키를 못 읽게 해요
    SESSION_COOKIE_SAMESITE="Lax",     # 다른 사이트에서 보낸 요청에는 로그인 쿠키를 안 붙여요
    SESSION_COOKIE_SECURE=HTTPS,       # HTTPS일 때는 로그인 쿠키를 암호화된 연결로만 보내요
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=16 * 1024,      # 요청이 16KB보다 크면 거절해요
)
if HTTPS:
    # Render 는 앞에 있는 '중계 서버'가 HTTPS를 처리하고 우리 앱에 넘겨줘요.
    # 중계 서버가 알려 주는 원래 주소(https)와 접속한 사람의 IP를 믿도록 해요 (1단계만)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# AI는 CPU 하나를 다 써서, 질문은 한 번에 하나씩만 처리해요
_busy = threading.Lock()
# 로그인 실패 기록 {아이디: [틀린 횟수, 처음 틀린 시각]}
_login_fails: dict[str, list] = {}
_login_fails_lock = threading.Lock()
# 없는 아이디로 로그인할 때도 비밀번호 확인 시간을 똑같이 쓰려고 만든 가짜 값
# (시간 차이로 "이 아이디가 있구나"를 알아채지 못하게 해요)
_DUMMY_HASH = generate_password_hash(secrets.token_hex(16))


def _json_body() -> dict | None:
    """JSON으로 보낸 요청만 받아요. 아니면 None."""
    if not request.is_json:
        return None
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def _error(message: str, status: int):
    return jsonify(error=message), status


def login_required(view):
    """로그인한 사람만 쓸 수 있게 막아 주는 장치예요."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        user_id = session.get("uid")
        if user_id is None or db.get_user(user_id) is None:
            session.clear()
            return _error("로그인이 필요해요.", 401)
        return view(user_id, *args, **kwargs)
    return wrapper


def _log_in(user_id: int) -> None:
    session.clear()  # 로그인할 때마다 세션을 새로 만들어요
    session["uid"] = user_id
    session.permanent = True  # 브라우저를 닫아도 30일 동안 로그인이 유지돼요


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/fonts/<path:name>")
def fonts(name: str):
    """글꼴 파일(G마켓 산스)을 보내요. 한 번 받으면 브라우저가 1년 동안 기억해서 다시 받지 않아요."""
    return send_from_directory(WEB_DIR / "fonts", name, max_age=365 * 24 * 3600)


@app.get("/google<token>.html")
def google_site_verification(token: str):
    """Google Search Console 사이트 확인 파일(web/google○○○.html)을 보내요. 그 이름의 파일만 보내요."""
    return send_from_directory(WEB_DIR, f"google{token}.html")


@app.get("/healthz")
def healthz():
    """서버가 살아 있는지 확인하는 주소예요. Render 가 가끔 들러서 확인해요."""
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# 회원가입 / 로그인
# ---------------------------------------------------------------------------

@app.post("/api/signup")
def signup():
    body = _json_body()
    if body is None:
        return _error("잘못된 요청이에요.", 415)
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    if not USERNAME_PATTERN.fullmatch(username):
        return _error("아이디는 한글, 영어, 숫자, _ 로 2~20글자로 만들어 주세요.", 400)
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        return _error(f"비밀번호는 {PASSWORD_MIN}글자 이상으로 만들어 주세요.", 400)

    # 비밀번호는 원래 글자 대신, 되돌릴 수 없게 바꾼 값(해시)만 저장해요
    user_id = db.create_user(username, generate_password_hash(password))
    if user_id is None:
        return _error("이미 있는 아이디예요. 다른 아이디를 써 주세요.", 409)
    _log_in(user_id)
    return jsonify(username=username), 201


@app.post("/api/login")
def login():
    body = _json_body()
    if body is None:
        return _error("잘못된 요청이에요.", 415)
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    key = username.lower()

    with _login_fails_lock:
        count, first = _login_fails.get(key, [0, 0.0])
        if time.monotonic() - first > LOGIN_LOCK_SECONDS:
            count = 0  # 오래전에 틀린 건 잊어요
        if count >= LOGIN_MAX_FAILS:
            return _error("로그인을 여러 번 틀려서 잠시 막았어요. 5분 뒤에 다시 해 주세요.", 429)

    user = db.find_user(username) if username else None
    password_ok = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, password)
    if not (user and password_ok):
        with _login_fails_lock:
            count, first = _login_fails.get(key, [0, 0.0])
            if count == 0 or time.monotonic() - first > LOGIN_LOCK_SECONDS:
                _login_fails[key] = [1, time.monotonic()]
            else:
                _login_fails[key][0] += 1
        # 아이디가 틀렸는지 비밀번호가 틀렸는지는 알려 주지 않아요 (아이디 알아내기 막기)
        return _error("아이디 또는 비밀번호가 맞지 않아요.", 401)

    with _login_fails_lock:
        _login_fails.pop(key, None)
    _log_in(user["id"])
    return jsonify(username=user["username"])


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
@login_required
def me(user_id: int):
    return jsonify(username=db.get_user(user_id)["username"])


# ---------------------------------------------------------------------------
# 대화 기록
# ---------------------------------------------------------------------------

@app.get("/api/conversations")
@login_required
def conversations(user_id: int):
    return jsonify(conversations=db.list_conversations(user_id))


@app.get("/api/conversations/<int:conversation_id>")
@login_required
def conversation(user_id: int, conversation_id: int):
    if not db.owns_conversation(user_id, conversation_id):
        return _error("대화를 찾을 수 없어요.", 404)  # 남의 대화도 '없다'고 해요
    return jsonify(id=conversation_id, turns=db.get_turns(conversation_id))


@app.delete("/api/conversations/<int:conversation_id>")
@login_required
def delete_conversation(user_id: int, conversation_id: int):
    if not db.delete_conversation(user_id, conversation_id):
        return _error("대화를 찾을 수 없어요.", 404)
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# 질문하기
# ---------------------------------------------------------------------------

@app.post("/ask")
@login_required
def ask(user_id: int):
    """질문을 받아서, 진행 상황과 답을 한 줄에 하나씩(JSON) 바로바로 보내요.

    답이 끝나면 질문과 답을 DB에 저장해요. 같은 대화방에서 이어서 물으면 이전 대화를 기억해요.
    """
    body = _json_body()
    if body is None:
        return _error("잘못된 요청이에요.", 415)
    question = " ".join(str(body.get("question", "")).split())[:MAX_QUESTION_CHARS]
    if not question:
        return _error("질문이 비어 있어요.", 400)

    conversation_id = body.get("conversation_id")
    if conversation_id is not None:
        if not isinstance(conversation_id, int) or not db.owns_conversation(user_id, conversation_id):
            return _error("대화를 찾을 수 없어요.", 404)
        history = db.recent_history(conversation_id, brain.HISTORY_TURNS)
    else:
        # 새 대화방을 만들어요. 제목은 첫 질문 앞부분이에요
        conversation_id = db.create_conversation(user_id, question[:40])
        history = []

    def line(event: dict) -> str:
        return json.dumps(event, ensure_ascii=False) + "\n"

    def events():
        yield line({"type": "conversation", "id": conversation_id})
        # 다른 질문을 처리하는 중이면 끝날 때까지 기다려요
        if not _busy.acquire(blocking=False):
            started = time.monotonic()
            yield line({"type": "step", "text": "앞 질문이 끝나기를 기다리는 중"})
            _busy.acquire()
            yield line({"type": "done", "note": "", "sec": time.monotonic() - started})
        started, quick = time.monotonic(), None
        try:
            for event in run(question, history):
                if event["type"] == "quick":
                    quick = event["quick"]
                elif event["type"] == "result":
                    db.add_turn(conversation_id, question, event["question"], event["result"]["answer"],
                                quick=quick, result=event["result"], seconds=event["sec"])
                yield line(event)
        except (SearchError, BrainError) as e:
            db.add_turn(conversation_id, question, question, str(e), quick=quick,
                        seconds=time.monotonic() - started, ok=False)
            yield line({"type": "error", "message": str(e)})
        except Exception:
            traceback.print_exc()  # 자세한 내용은 이 창(터미널)에 남겨요
            yield line({"type": "error", "message": "알 수 없는 문제가 생겼어요. 잠시 뒤에 다시 해 보세요."})
        finally:
            _busy.release()

    return Response(
        events(),
        mimetype="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main() -> None:
    # 처음 질문하기 전에 AI 모델을 미리 불러 둬요 (이 컴퓨터의 Ollama일 때 약 20초)
    threading.Thread(target=brain.warm_up, daemon=True).start()

    url = f"http://{HOST}:{PORT}"
    print(f"ssayuz AI 웹 화면: {url}")
    print("끝내려면 이 창에서 Ctrl+C를 누르세요.")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, webbrowser.open, args=[url]).start()
    # threaded=True: 답을 쓰는 동안에도 화면 요청을 받을 수 있어요
    app.run(host=HOST, port=PORT, threaded=True)


if __name__ == "__main__":
    main()
