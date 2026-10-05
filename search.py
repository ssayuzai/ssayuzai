r"""
2단계: 검색만 하는 프로그램이에요.
DuckDuckGo에서 검색해서 제목 / 링크 / 요약을 보여줘요.

실행: .venv\Scripts\python.exe search.py 목성의 위성
"""

import sys
from urllib.parse import urlparse

from ddgs.engines.duckduckgo import Duckduckgo

# 한국어 결과를 먼저 보여 달라는 지역 설정이에요
REGION = "kr-kr"
# DuckDuckGo 세이프서치 단계: 1 = 엄격, -1 = 보통, -2 = 끔
SAFE_SEARCH = "1"
# 검색이 이 시간(초)보다 오래 걸리면 포기해요
TIMEOUT = 10
# 세이프서치 두 번째 안전망: 사이트 주소에 이 말이 들어 있으면 결과에서 빼요
# ("sex"는 Sussex, Essex 같은 정상 주소까지 막아서 넣지 않았어요)
BLOCKED_HOST_WORDS = (
    "porn", "xvideos", "xnxx", "xhamster", "redtube", "youporn",
    "onlyfans", "chaturbate", "spankbang", "hentai",
)


class SearchError(Exception):
    """검색이 실패했을 때 쓰는 오류예요 (인터넷 끊김, DuckDuckGo 차단 등)."""


class SafeDuckDuckGo(Duckduckgo):
    """세이프서치를 항상 켠 DuckDuckGo 검색기예요.

    ddgs 9.16.0의 DuckDuckGo 검색기는 safesearch 설정을 받기만 하고 쓰지 않아요.
    지역도 DuckDuckGo가 모르는 이름(l)으로 보내서 '전 세계'로 검색돼요.
    그래서 DuckDuckGo가 알아듣는 이름(kp = 세이프서치, kl = 지역)으로 직접 붙여 줘요.
    (ddgs의 다른 검색엔진인 구글·빙 등은 쓰지 않고 DuckDuckGo만 써요.)
    """

    def build_payload(self, *args, **kwargs):
        payload = super().build_payload(*args, **kwargs)
        payload["kp"] = SAFE_SEARCH
        payload["kl"] = payload["l"]
        return payload


def is_blocked(url: str) -> bool:
    """성인 사이트처럼 보이는 주소면 True 를 돌려줘요."""
    host = urlparse(url).netloc.lower()
    return any(word in host for word in BLOCKED_HOST_WORDS)


def search(query: str, max_results: int = 5) -> list[dict]:
    """검색어를 DuckDuckGo에 물어보고 결과를 돌려줘요.

    돌려주는 모양: [{"title": 제목, "url": 링크, "snippet": 짧은 요약}, ...]
    결과가 하나도 없으면 빈 목록 [] 을 돌려줘요.
    """
    engine = SafeDuckDuckGo(timeout=TIMEOUT)
    try:
        results = engine.search(query, region=REGION)
    except Exception as e:  # 인터넷 연결 문제, 시간 초과 등
        raise SearchError(f"검색 중 문제가 생겼어요: {e}") from e

    # None 이면 DuckDuckGo가 정상 응답을 주지 않은 거예요 (너무 자주 검색해서 잠깐 막힌 경우 등)
    if results is None:
        raise SearchError("DuckDuckGo가 잠시 검색을 막았어요. 1~2분 뒤에 다시 해 보세요.")

    found = []
    seen = set()  # 같은 링크가 두 번 나오지 않게 기억해 둬요
    for r in results:
        if not r.href or r.href in seen or is_blocked(r.href):
            continue
        seen.add(r.href)
        found.append({"title": r.title, "url": r.href, "snippet": r.body})
        if len(found) >= max_results:
            break
    return found


if __name__ == "__main__":
    # 명령어 뒤에 적은 말을 검색어로 써요. 없으면 직접 물어봐요.
    query = " ".join(sys.argv[1:]) or input("검색어: ").strip()
    if not query:
        sys.exit("검색어가 비어 있어요.")

    try:
        items = search(query)
    except SearchError as e:
        sys.exit(str(e))

    if not items:
        print("검색 결과가 없어요.")
    for i, item in enumerate(items, start=1):
        print(f"[{i}] {item['title']}")
        print(f"    {item['url']}")
        print(f"    {item['snippet']}")
        print()
