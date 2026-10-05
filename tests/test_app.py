r"""
웹 서버(app.py)와 DB(db.py)를 자동으로 시험해요. AI와 인터넷은 쓰지 않아서 몇 초면 끝나요.

실행: .venv\Scripts\python.exe -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# 진짜 DB(data/ssayuz.db)를 건드리지 않게, 임시 폴더에 시험용 DB를 만들어요
_tmp = tempfile.TemporaryDirectory()
os.environ["SSAYUZ_DATA_DIR"] = _tmp.name
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as web  # noqa: E402  (위에서 폴더를 정한 다음에 불러와야 해요)
from search import SearchError  # noqa: E402

# 시험용 계정 (이 시험 안에서만 쓰는 값이에요)
ALICE = {"username": "tester_alice", "password": "test-pass-1234"}
BOB = {"username": "tester_bob", "password": "test-pass-5678"}

FAKE_RESULT = {
    "answer": "세종대왕은 1397년에 태어났어요[1].",
    "sources": [{"n": 1, "title": "세종 - 위키백과", "url": "https://ko.wikipedia.org/wiki/세종"}],
    "cited": [1],
    "dropped": [],
    "stats": {},
}
FAKE_QUICK = {"quotes": [{"n": 1, "text": "1397년 5월 15일에 태어났다."}], "sources": FAKE_RESULT["sources"]}


def fake_run(question, history=()):
    """진짜 run 대신 쓰는 가짜예요. 받은 이전 대화를 기록해 둬요."""
    fake_run.last_history = list(history)
    understood = f"{question} (이해함)" if history else question
    yield {"type": "step", "text": "검색하는 중"}
    yield {"type": "done", "note": "결과 1개", "sec": 0.1}
    yield {"type": "quick", "quick": FAKE_QUICK, "sec": 0.2}
    yield {"type": "result", "result": FAKE_RESULT, "question": understood, "sec": 0.3}


def blocked_run(question, history=()):
    yield {"type": "step", "text": "검색하는 중"}
    raise SearchError("DuckDuckGo가 잠시 검색을 막았어요.")


class AppTest(unittest.TestCase):
    def setUp(self):
        web.db.init()
        with web.db.connect() as conn:  # 시험마다 깨끗한 DB에서 시작해요
            conn.executescript("DELETE FROM turns; DELETE FROM conversations; DELETE FROM users;")
        web._login_fails.clear()
        web.run = fake_run
        self.client = web.app.test_client()

    def signup(self, user=ALICE, client=None):
        return (client or self.client).post("/api/signup", json=user)

    def ask(self, question, conversation_id=None, client=None):
        response = (client or self.client).post("/ask", json={"question": question, "conversation_id": conversation_id})
        events = [json.loads(line) for line in response.get_data(as_text=True).splitlines()] if response.status_code == 200 else []
        return response, events

    # ---------- 회원가입 / 로그인 ----------

    def test_signup_validates_input(self):
        self.assertEqual(self.client.post("/api/signup", json={"username": "a", "password": "test-pass-1234"}).status_code, 400)
        self.assertEqual(self.client.post("/api/signup", json={"username": "bad name!", "password": "test-pass-1234"}).status_code, 400)
        self.assertEqual(self.client.post("/api/signup", json={"username": "tester_short", "password": "short"}).status_code, 400)
        self.assertEqual(self.client.post("/api/signup", data="username=x").status_code, 415)  # JSON이 아니면 거절

    def test_signup_logs_in_and_rejects_duplicates(self):
        self.assertEqual(self.signup().status_code, 201)
        self.assertEqual(self.client.get("/api/me").get_json()["username"], ALICE["username"])
        other = web.app.test_client()
        dup = {"username": ALICE["username"].upper(), "password": "another-pass-99"}
        self.assertEqual(other.post("/api/signup", json=dup).status_code, 409)  # 대소문자만 달라도 같은 아이디

    def test_password_is_not_stored_as_plain_text(self):
        self.signup()
        stored = web.db.find_user(ALICE["username"])["password_hash"]
        self.assertNotIn(ALICE["password"], stored)
        self.assertTrue(stored.startswith("scrypt:"))

    def test_login_logout(self):
        self.signup()
        self.client.post("/api/logout")
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={**ALICE, "password": "wrong-password"}).status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={"username": "nobody_here", "password": "x" * 8}).status_code, 401)
        self.assertEqual(self.client.post("/api/login", json=ALICE).status_code, 200)
        self.assertEqual(self.client.get("/api/me").status_code, 200)

    def test_login_locks_after_repeated_failures(self):
        self.signup()
        self.client.post("/api/logout")
        for _ in range(web.LOGIN_MAX_FAILS):
            self.client.post("/api/login", json={**ALICE, "password": "wrong-password"})
        # 많이 틀린 뒤에는 맞는 비밀번호도 잠시 막혀요
        self.assertEqual(self.client.post("/api/login", json=ALICE).status_code, 429)

    def test_invite_code_is_required_when_set(self):
        self.assertFalse(self.client.get("/api/config").get_json()["invite_required"])
        os.environ["SSAYUZ_INVITE_CODE"] = "test-invite-42"
        try:
            self.assertTrue(self.client.get("/api/config").get_json()["invite_required"])
            self.assertEqual(self.signup().status_code, 403)  # 코드 없이 가입하면 거절
            self.assertEqual(self.client.post("/api/signup", json={**ALICE, "invite_code": "wrong"}).status_code, 403)
            self.assertEqual(self.client.post("/api/signup", json={**ALICE, "invite_code": "test-invite-42"}).status_code, 201)
        finally:
            del os.environ["SSAYUZ_INVITE_CODE"]

    def test_health_check(self):
        self.assertEqual(self.client.get("/healthz").get_json(), {"ok": True})

    def test_fonts_are_served_and_cached(self):
        response = self.client.get("/fonts/GmarketSansTTFMedium.woff2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "font/woff2")
        self.assertIn("max-age=31536000", response.headers["Cache-Control"])
        response.close()
        self.assertEqual(self.client.get("/fonts/../app.py").status_code, 404)  # 다른 파일은 못 꺼내 가요

    # ---------- 질문하기와 기록 저장 ----------

    def test_ask_requires_login_and_json(self):
        self.assertEqual(self.ask("세종대왕은 언제 태어났어?")[0].status_code, 401)
        self.signup()
        self.assertEqual(self.client.post("/ask", data="question=x").status_code, 415)
        self.assertEqual(self.ask("   ")[0].status_code, 400)

    def test_ask_saves_history_and_remembers_previous_turns(self):
        self.signup()
        response, events = self.ask("세종대왕은 언제 태어났어?")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([e["type"] for e in events], ["conversation", "step", "done", "quick", "result"])
        conversation_id = events[0]["id"]
        self.assertEqual(fake_run.last_history, [])  # 첫 질문은 이전 대화가 없어요

        # 같은 대화방에서 이어서 물으면 이전 질문과 답을 넘겨줘요
        self.ask("그럼 이순신은?", conversation_id)
        self.assertEqual(fake_run.last_history, [{"question": "세종대왕은 언제 태어났어?", "answer": FAKE_RESULT["answer"]}])

        listed = self.client.get("/api/conversations").get_json()["conversations"]
        self.assertEqual([c["id"] for c in listed], [conversation_id])
        turns = self.client.get(f"/api/conversations/{conversation_id}").get_json()["turns"]
        self.assertEqual([t["question"] for t in turns], ["세종대왕은 언제 태어났어?", "그럼 이순신은?"])
        self.assertEqual(turns[1]["understood"], "그럼 이순신은? (이해함)")
        self.assertEqual(turns[0]["quick"], FAKE_QUICK)
        self.assertEqual(turns[0]["cited"], [1])

    def test_failed_search_is_saved_as_error(self):
        self.signup()
        web.run = blocked_run
        _, events = self.ask("목성의 위성은 몇 개야?")
        self.assertEqual(events[-1]["type"], "error")
        turns = web.db.get_turns(events[0]["id"])
        self.assertFalse(turns[0]["ok"])
        self.assertFalse(web._busy.locked())  # 오류가 나도 다음 질문을 받을 수 있어요

    def test_users_cannot_see_each_others_conversations(self):
        self.signup()
        _, events = self.ask("세종대왕은 언제 태어났어?")
        conversation_id = events[0]["id"]

        bob = web.app.test_client()
        self.signup(BOB, bob)
        self.assertEqual(bob.get(f"/api/conversations/{conversation_id}").status_code, 404)
        self.assertEqual(bob.delete(f"/api/conversations/{conversation_id}").status_code, 404)
        self.assertEqual(self.ask("몰래 이어 묻기", conversation_id, bob)[0].status_code, 404)
        self.assertEqual(bob.get("/api/conversations").get_json()["conversations"], [])

    def test_delete_conversation(self):
        self.signup()
        _, events = self.ask("세종대왕은 언제 태어났어?")
        conversation_id = events[0]["id"]
        self.assertEqual(self.client.delete(f"/api/conversations/{conversation_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/conversations/{conversation_id}").status_code, 404)
        self.assertEqual(web.db.get_turns(conversation_id), [])  # 기록도 함께 지워져요


if __name__ == "__main__":
    unittest.main()
