r"""
3단계: 웹페이지에서 본문(진짜 내용)만 뽑아내는 프로그램이에요.
메뉴, 광고, 댓글 같은 건 빼고 글 내용만 남겨요.

실행: .venv\Scripts\python.exe reader.py https://ko.wikipedia.org/wiki/목성의_위성
      .venv\Scripts\python.exe reader.py 목성의 위성은 몇 개야   (검색해서 위에서부터 읽기)
"""

import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from urllib.parse import urlparse

import requests
import trafilatura
from protego import Protego

# 우리 프로그램 이름표. 사이트에 "저는 ssayuz AI예요"라고 솔직하게 알려요
BOT_NAME = "ssayuzAI"
HEADERS = {
    "User-Agent": f"Mozilla/5.0 (compatible; {BOT_NAME}/0.1)",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}
# 한 페이지를 받는 데 이 시간(초)보다 오래 걸리면 건너뛰어요
TIMEOUT = 8
# 이보다 큰 페이지(3MB)는 너무 무거워서 건너뛰어요
MAX_BYTES = 3_000_000
# 본문이 이보다 짧으면 쓸 만한 내용이 없다고 보고 건너뛰어요
MIN_CHARS = 200
# 깐깐하게 뽑은 본문이 이보다 짧으면 넉넉하게 한 번 더 뽑아 봐요
SHORT_CHARS = 1000
# AI에게 넘길 본문 길이 (작은 AI는 한 번에 많이 못 읽어요)
MAX_CHARS = 4000
# 여러 페이지를 동시에 받을 때, 전체로 이 시간(초)이 지나면 받은 것만 써요
# (CPU가 아주 작은 무료 서버에서는 본문 뽑기가 느려서 SSAYUZ_READ_DEADLINE 으로 늘릴 수 있어요)
READ_DEADLINE = float(os.environ.get("SSAYUZ_READ_DEADLINE", 7))
# 못 읽는 페이지를 생각해서 필요한 수보다 이만큼 더 받아 봐요
EXTRA_PAGES = 3


class ReadError(Exception):
    """페이지를 읽지 못했을 때 쓰는 오류예요. 이유를 함께 담아요."""


def fix_url(url: str) -> str:
    """읽기 쉬운 주소로 바꿔요.

    네이버 블로그(PC)는 본문이 안쪽 창(iframe)에 숨어 있어서 바로 못 읽어요.
    모바일 주소(m.blog.naver.com)는 본문이 바로 들어 있어서 그쪽으로 바꿔요.
    """
    parts = urlparse(url)
    if parts.netloc == "blog.naver.com":
        return parts._replace(netloc="m.blog.naver.com").geturl()
    return url


# 사이트마다 robots.txt 를 한 번만 받으려고 기억해 두는 곳이에요
_robots_cache: dict[str, Protego | None] = {}
# "전부 금지" 규칙
_DISALLOW_ALL = Protego.parse("User-agent: *\nDisallow: /")


def _robots_for(site: str) -> Protego | None:
    """사이트의 robots.txt(로봇 출입 규칙)를 받아 와요. None 이면 규칙이 없다는 뜻이에요."""
    if site in _robots_cache:
        return _robots_cache[site]
    try:
        resp = requests.get(f"{site}/robots.txt", headers=HEADERS, timeout=5)
    except requests.RequestException as e:
        # 규칙 파일조차 못 받는 사이트는 본문도 못 받을 테니 바로 건너뛰어요
        raise ReadError(f"사이트에 연결하지 못했어요 ({type(e).__name__})") from e

    if resp.status_code == 200:
        rules = Protego.parse(resp.text)
    elif resp.status_code in (401, 403) or resp.status_code >= 500:
        rules = _DISALLOW_ALL  # 규칙을 못 보게 하거나 서버가 고장 났으면 금지로 봐요
    else:
        rules = None  # 규칙 파일이 없으면(404 등) 들어가도 돼요
    _robots_cache[site] = rules
    return rules


def allowed_by_robots(url: str) -> bool:
    """이 주소를 읽어도 된다고 사이트가 허락했는지 확인해요.

    표준 규칙(RFC 9309)대로 더 자세하게 적힌 줄을 따라요.
    예) "Allow: /" 와 "Disallow: /api/" 가 같이 있으면 /api/ 는 금지예요.
    """
    parts = urlparse(url)
    rules = _robots_for(f"{parts.scheme}://{parts.netloc}")
    return rules is None or rules.can_fetch(url, BOT_NAME)


def _download(url: str) -> bytes:
    """페이지를 받아요. 너무 느리거나, 너무 크거나, 웹페이지가 아니면 포기해요."""
    deadline = time.monotonic() + TIMEOUT
    try:
        with requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True) as resp:
            if resp.status_code != 200:
                raise ReadError(f"사이트가 거절했어요 (HTTP {resp.status_code})")
            if "html" not in resp.headers.get("Content-Type", ""):
                raise ReadError("웹페이지(HTML)가 아니에요")
            data = b""
            # 조금씩 받으면서 시간과 크기를 계속 확인해요
            for chunk in resp.iter_content(chunk_size=65536):
                data += chunk
                if len(data) > MAX_BYTES:
                    raise ReadError("페이지가 너무 커요")
                if time.monotonic() > deadline:
                    raise ReadError("너무 오래 걸려요")
            return data
    except requests.RequestException as e:
        raise ReadError(f"연결 문제: {type(e).__name__}") from e


def read_page(url: str, max_chars: int = MAX_CHARS) -> str:
    """주소 하나를 받아서 본문 글자만 돌려줘요. 못 읽으면 ReadError 를 내요."""
    url = fix_url(url)
    if not allowed_by_robots(url):
        raise ReadError("사이트가 로봇 출입을 막아 뒀어요 (robots.txt)")

    raw = _download(url)
    # 먼저 깐깐하게 뽑아요. 너무 짧으면(레시피 사이트 등) 덜 깐깐하게 한 번 더 뽑아서 긴 쪽을 써요
    text = _extract(raw, url, favor_precision=True)
    if len(text) < SHORT_CHARS:
        text = max(text, _extract(raw, url, favor_recall=True), key=len)
    # 위키백과의 각주 번호 [1][2]는 AI가 붙일 출처 번호와 헷갈려서 지워요
    # (다른 사이트는 코드 속 a[1] 같은 게 망가질 수 있어서 위키백과만 해요)
    if urlparse(url).netloc.endswith("wikipedia.org"):
        text = re.sub(r"\[\d+\]", "", text)
    if len(text) < MIN_CHARS:
        raise ReadError("본문을 찾지 못했어요")
    return text[:max_chars]


def _extract(raw: bytes, url: str, **mode) -> str:
    """받은 페이지에서 본문 글자만 골라내요."""
    # trafilatura 가 글자 인코딩(한글 깨짐 방지)도 알아서 맞추고, 본문만 골라내요
    text = trafilatura.extract(
        raw,
        url=url,
        include_comments=False,  # 댓글은 빼요
        include_tables=True,     # 표는 정보가 많아서 남겨요
        deduplicate=True,        # 같은 문장이 반복되면 한 번만
        **mode,                  # favor_precision(깐깐하게) 또는 favor_recall(넉넉하게)
    ) or ""
    # 탭, 연속된 빈칸, 여러 줄 빈 줄을 정리해서 AI가 읽을 글자 수를 아껴요
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def read_results(results: list[dict], want: int = 3, on_skip=None) -> list[dict]:
    """검색 결과 위쪽 페이지들을 **동시에** 받아서, 읽은 것 중 순위가 높은 want 개를 골라요.

    한 개씩 차례로 받으면 느린 페이지 하나 때문에 모두 기다려야 해요.
    그래서 여러 개를 한꺼번에 받고, 전체로 READ_DEADLINE 초가 지나면 받은 것만 써요.
    on_skip(주소, 이유)를 주면 건너뛴 페이지를 알려 줘요.
    돌려주는 모양: [{"title": 제목, "url": 링크, "snippet": 검색 요약, "text": 본문}, ...]
    """
    candidates = results[: want + EXTRA_PAGES]  # 못 읽는 페이지를 생각해서 몇 개 더 받아요
    pool = ThreadPoolExecutor(max_workers=len(candidates) or 1)
    futures = {pool.submit(read_page, item["url"]): rank for rank, item in enumerate(candidates)}
    texts = {}
    try:
        for future in as_completed(futures, timeout=READ_DEADLINE):
            rank = futures[future]
            try:
                texts[rank] = future.result()
            except ReadError as e:
                if on_skip:
                    on_skip(candidates[rank]["url"], str(e))
    except FuturesTimeout:
        if on_skip:
            for future, rank in futures.items():
                if not future.done():
                    on_skip(candidates[rank]["url"], "너무 오래 걸려요")
    finally:
        # 아직 안 끝난 페이지는 기다리지 않아요
        pool.shutdown(wait=False, cancel_futures=True)

    pages = []
    for rank in sorted(texts)[:want]:  # 검색 순위가 높은 것부터
        item = candidates[rank]
        pages.append({"title": item["title"], "url": item["url"],
                      "snippet": item.get("snippet", ""), "text": texts[rank]})
    return pages


if __name__ == "__main__":
    arg = " ".join(sys.argv[1:]) or input("주소 또는 검색어: ").strip()
    if not arg:
        sys.exit("주소나 검색어를 적어 주세요.")

    if arg.startswith(("http://", "https://")):
        # 주소 하나만 읽기
        try:
            print(read_page(arg))
        except ReadError as e:
            sys.exit(f"읽지 못했어요: {e}")
    else:
        # 검색하고 결과 페이지들을 읽기
        from search import SearchError, search

        try:
            results = search(arg, max_results=8)
        except SearchError as e:
            sys.exit(str(e))
        start = time.monotonic()
        pages = read_results(results, want=3, on_skip=lambda url, why: print(f"  건너뜀: {url} ({why})"))
        print(f"\n페이지 {len(pages)}개 읽음 ({time.monotonic() - start:.1f}초)\n")
        for i, page in enumerate(pages, start=1):
            print(f"[{i}] {page['title']}")
            print(f"    {page['url']}")
            print(f"    글자 수 {len(page['text'])}자 / 앞부분: {page['text'][:150]!r}")
            print()
