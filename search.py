r"""
검색 프로그램이에요. DuckDuckGo에서 검색해서 제목 / 링크 / 요약을 보여줘요.
(DuckDuckGo가 안 될 때 Ollama 웹 검색으로 대신 찾는 예비 검색도 있어요. 기본은 꺼져 있어요)

실행: .venv\Scripts\python.exe search.py 목성의 위성
"""

import os
import sys
import time
from urllib.parse import urlparse

from ddgs.engines.duckduckgo import Duckduckgo

# 한국어 결과를 먼저 보여 달라는 지역 설정이에요
REGION = "kr-kr"
# DuckDuckGo 세이프서치 단계: 1 = 엄격, -1 = 보통, -2 = 끔
SAFE_SEARCH = "1"
# 검색이 이 시간(초)보다 오래 걸리면 포기해요
TIMEOUT = 10
# 예비 검색: "ollama" 로 정하면 DuckDuckGo가 안 될 때 Ollama 웹 검색을 써요 (OLLAMA_API_KEY 필요)
FALLBACK = os.environ.get("SSAYUZ_SEARCH_FALLBACK", "")
# DuckDuckGo가 한 번 안 되면, 이 시간(초) 동안은 바로 예비 검색을 써요 (매번 10초씩 기다리지 않게)
DUCKDUCKGO_RETRY_AFTER = 600
_duckduckgo_down_until = 0.0
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
    """검색어로 검색해서 결과를 돌려줘요.

    기본은 DuckDuckGo예요. DuckDuckGo가 안 될 때(인터넷 서버에서 막히는 경우 등)
    SSAYUZ_SEARCH_FALLBACK=ollama 로 켜 두면 Ollama 웹 검색으로 대신 찾아요.
    돌려주는 모양: [{"title": 제목, "url": 링크, "snippet": 짧은 요약, "engine": 검색엔진}, ...]
    결과가 하나도 없으면 빈 목록 [] 을 돌려줘요.
    """
    global _duckduckgo_down_until
    fallback_on = FALLBACK == "ollama" and bool(os.environ.get("OLLAMA_API_KEY"))
    # 방금 DuckDuckGo가 안 됐으면, 잠시 동안은 기다리지 않고 바로 예비 검색으로 가요
    if fallback_on and time.monotonic() < _duckduckgo_down_until:
        return _ollama_search(query, max_results)
    try:
        return _duckduckgo(query, max_results)
    except SearchError:
        if not fallback_on:
            raise
        _duckduckgo_down_until = time.monotonic() + DUCKDUCKGO_RETRY_AFTER
        return _ollama_search(query, max_results)


def _ollama_search(query: str, max_results: int) -> list[dict]:
    """Ollama 웹 검색(공식 API)으로 찾아요. OLLAMA_API_KEY 가 필요해요.

    결과에 페이지 본문(content)도 들어 있어서, 페이지를 다시 받지 않아도 돼요.
    세이프서치 설정은 없어서 성인 사이트 걸러내기(is_blocked)를 꼭 거쳐요.
    """
    import ollama  # 예비 검색을 쓸 때만 불러와요

    try:
        response = ollama.Client(host="https://ollama.com", timeout=TIMEOUT * 2).web_search(
            query, max_results=min(max_results, 10)
        )
    except Exception as e:
        raise SearchError(f"예비 검색(Ollama)도 실패했어요: {e}") from e

    found = []
    for r in response.results:
        if not r.url or is_blocked(r.url):
            continue
        content = r.content or ""
        found.append({"title": r.title or r.url, "url": r.url, "snippet": content[:300],
                      "content": content, "engine": "ollama"})
    return found


def _duckduckgo(query: str, max_results: int) -> list[dict]:
    """DuckDuckGo에 물어봐요 (세이프서치 엄격, 한국 지역)."""
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
        found.append({"title": r.title, "url": r.href, "snippet": r.body, "engine": "duckduckgo"})
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
