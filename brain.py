r"""
AI 두뇌예요. Ollama로 내 컴퓨터에서 돌아가는 AI와 대화해요.
  1) rewrite_question : 이어지는 질문("그럼 토성은?")을 혼자서도 뜻이 통하는 질문으로 바꾸기
  2) quick_answer     : AI 없이 원문에서 관련 문장을 골라 바로 보여 주기 (빠른 답)
  3) write_answer     : 읽은 페이지 → 출처 번호 [1][2]를 붙인 한국어 답 (AI 정리)

실행: .venv\Scripts\python.exe brain.py 목성의 위성은 몇 개야
"""

import json
import os
import re
import sys
from collections import Counter

import ollama

def api_key() -> str:
    """Ollama 클라우드 API 키를 읽어요.

    붙여 넣을 때 딸려 들어가기 쉬운 앞뒤 빈칸, 줄바꿈, 따옴표("키")는 떼어 내요.
    (이런 게 섞이면 Ollama가 '인증 실패(401)'로 거절해요)
    """
    return os.environ.get("OLLAMA_API_KEY", "").strip().strip("\"'").strip()


# 어떤 AI를 쓸지는 '환경 변수'로 정해요. 코드를 고치지 않고 컴퓨터마다 다르게 쓸 수 있어요.
#   OLLAMA_API_KEY 가 있으면 → Ollama 클라우드(ollama.com)의 AI
#   없으면                  → 이 컴퓨터에 설치한 Ollama의 AI
CLOUD = bool(api_key())
# 우리가 쓸 AI 모델 (상업적으로 써도 되는 Apache 2.0 모델)
# 클라우드에는 qwen3.5:2b 가 없어서 기본 모델이 달라요. SSAYUZ_MODEL 로 바꿀 수 있어요
MODEL = os.environ.get("SSAYUZ_MODEL", "gemma4:31b" if CLOUD else "qwen3.5:2b")
# 모델을 30분 동안 메모리에 올려 둬요. 다시 불러오는 시간(약 24초)을 아껴요 (이 컴퓨터에서만)
KEEP_ALIVE = "30m"
# AI가 한 번에 볼 수 있는 글의 양(토큰). 자료 + 질문 + 답이 이 안에 들어가야 해요
NUM_CTX = 8192
# AI에게 보여 줄 자료의 총 글자 수.
# 이 컴퓨터(CPU)는 AI가 글을 1초에 약 27토큰(한글 약 48자)밖에 못 읽어서 아껴 써요.
# 클라우드는 GPU라서 빠르니까 2배로 보여 줘요 (자료가 많을수록 답이 정확해져요)
CONTEXT_CHARS = int(os.environ.get("SSAYUZ_CONTEXT_CHARS", 3000 if CLOUD else 1500))
# 본문을 이 크기의 문단 조각으로 잘라서, 질문과 관련 있는 조각만 골라요
CHUNK_CHARS = 300
# 답의 최대 길이(토큰). 너무 길게 쓰지 않게 막아요
MAX_ANSWER_TOKENS = 250
# 빠른 답에 보여 줄 원문 문장 수
QUICK_SENTENCES = 3
# 이어지는 질문을 이해할 때 볼 이전 대화 수
HISTORY_TURNS = 2
# 자료에 답이 없을 때 하는 말
NOT_FOUND = "찾지 못했어요"

# 지시문은 질문할 때마다 AI가 처음부터 다시 읽어요(약 14초/400토큰). 그래서 짧게 썼어요.
# 작은 AI는 설명보다 예시를 잘 따라 해서 예시를 하나 넣었어요. 실제 답에 섞이지 않게 지어낸 마을이에요.
ANSWER_RULES = """[자료]에 있는 내용만으로 [질문]에 한국어 2~4문장으로 짧게 답해.
- 문장마다 끝에 근거 자료 번호를 [1]처럼 붙여.
- 자료끼리 다르면 최근 자료를 먼저 말해.
- 자료에 답이 없으면 "찾지 못했어요"라고만 해.
예) [자료 1] 별빛마을 축제는 매년 5월에 열린다. [질문] 별빛마을 축제는 언제야? 답: 별빛마을 축제는 매년 5월에 열려요[1]."""

REWRITE_RULES = """이전 대화를 보고, 마지막 질문을 혼자 읽어도 뜻이 통하는 완전한 질문으로 바꿔. 이미 완전하면 그대로 써.
예1) 이전 질문: 목성의 위성은 몇 개야? / 마지막 질문: 그럼 토성은? → {"question": "토성의 위성은 몇 개야?"}
예2) 이전 질문: 에펠탑 높이는 얼마야? / 마지막 질문: 언제 지어졌어? → {"question": "에펠탑은 언제 지어졌어?"}
예3) 이전 질문: 에펠탑 높이는 얼마야? / 마지막 질문: 김치찌개 끓이는 법 → {"question": "김치찌개 끓이는 법"}"""

# AI 서버(Ollama)와 연결하는 통로. 답을 쓰는 데 몇 분 걸릴 수 있어서 넉넉히 기다려요.
# 클라우드일 때는 깨끗하게 정리한 API 키를 '출입증'(authorization)으로 붙여요
_client = ollama.Client(
    host=os.environ.get("OLLAMA_HOST") or ("https://ollama.com" if CLOUD else None),
    timeout=600,
    headers={"authorization": f"Bearer {api_key()}"} if CLOUD else None,
)
# 모델에 '속으로 생각하기' 기능이 있는지 기억해 둬요 (처음 한 번만 물어봐요)
_thinking_supported: bool | None = None


class BrainError(Exception):
    """AI와 대화하다 문제가 생겼을 때 쓰는 오류예요."""


def _supports_thinking() -> bool:
    """이 모델에 '속으로 생각하기' 기능이 있는지 알아봐요.

    있으면 꺼야 빨라요. 없는 모델에 끄라고 하면 오류가 날 수 있어서 먼저 확인해요.
    """
    global _thinking_supported
    if _thinking_supported is None:
        try:
            _thinking_supported = "thinking" in (_client.show(MODEL).capabilities or [])
        except Exception:
            return False  # 확인하지 못했으면 이번에는 끄지 않고, 다음에 다시 확인해요
    return _thinking_supported


def _chat(messages: list[dict], stream: bool = False, **kwargs):
    """Ollama에 말을 걸어요. 연결이 안 되면 알아듣기 쉬운 오류로 바꿔요."""
    options = {
        "temperature": 0.2,      # 낮을수록 차분하고 정확하게 답해요
        "presence_penalty": 0,   # 기본값(1.5)은 [1] 같은 출처 번호 반복을 싫어해서 꺼요
        "num_ctx": NUM_CTX,
    }
    options.update(kwargs.pop("options", {}))
    if _supports_thinking():
        kwargs["think"] = False  # '속으로 생각하기'를 끄면 훨씬 빨라요
    if not CLOUD:
        kwargs["keep_alive"] = KEEP_ALIVE
    try:
        return _client.chat(model=MODEL, messages=messages, stream=stream, options=options, **kwargs)
    except (ConnectionError, ollama.ResponseError) as e:
        raise _friendly_error(e) from e


def _friendly_error(e: Exception) -> BrainError:
    """Ollama 오류를 알아듣기 쉬운 말로 바꿔요."""
    if isinstance(e, ConnectionError):
        if CLOUD:
            return BrainError("Ollama 클라우드에 연결하지 못했어요. 잠시 뒤에 다시 해 보세요.")
        return BrainError("Ollama가 꺼져 있어요. Ollama를 켜고 다시 해 보세요.")
    status = getattr(e, "status_code", None)
    if CLOUD and status in (401, 403):
        return BrainError("Ollama 클라우드 API 키가 맞지 않거나, 이 모델을 쓸 권한이 없어요. "
                          "OLLAMA_API_KEY 에 키만 정확히 들어 있는지 확인해 주세요.")
    if CLOUD and status == 429:
        return BrainError("Ollama 클라우드 무료 사용량을 다 썼거나 너무 자주 물어봤어요. 잠시 뒤에 다시 해 보세요.")
    if status == 404:
        if CLOUD:
            return BrainError(f"Ollama 클라우드에 '{MODEL}' 모델이 없어요. SSAYUZ_MODEL 설정을 확인해 주세요.")
        return BrainError(f"모델이 없어요. 먼저 받아 주세요: ollama pull {MODEL}")
    return BrainError(f"AI 오류: {e}")


def warm_up() -> None:
    """모델을 미리 메모리에 올려 둬요. 검색하는 동안 불러 두면 기다리는 시간이 줄어요."""
    if CLOUD:
        return  # 클라우드는 미리 불러 둘 필요가 없어요
    try:
        # num_ctx 가 실제 대화와 다르면 Ollama가 모델을 다시 불러와서 시간이 두 배로 들어요
        _client.generate(model=MODEL, prompt="", keep_alive=KEEP_ALIVE, options={"num_ctx": NUM_CTX})
    except Exception:
        pass  # 미리 불러오기는 실패해도 괜찮아요. 실제로 쓸 때 다시 불러요


# ---------------------------------------------------------------------------
# 1) 이어지는 질문 이해하기
# ---------------------------------------------------------------------------

def rewrite_question(question: str, history: list[dict]) -> str:
    """이어지는 질문을 혼자서도 뜻이 통하는 질문으로 바꿔요.

    history : [{"question": 이전 질문, "answer": 이전 답}, ...] (오래된 것부터)
    예) 이전 질문 "목성의 위성은 몇 개야?" + 지금 질문 "그럼 토성은?" → "토성의 위성은 몇 개야?"
    이전 대화가 없거나 AI가 이상하게 답하면 질문을 그대로 돌려줘요.
    """
    if not history:
        return question
    lines = []
    for turn in history[-HISTORY_TURNS:]:
        # 답은 출처 번호를 빼고 앞부분만 보여 줘요. 길게 보여 주면 AI가 읽는 시간이 늘어요
        short_answer = re.sub(r"\[\d+\]", "", turn["answer"])[:80]
        lines.append(f"이전 질문: {turn['question']}")
        lines.append(f"이전 답: {short_answer}")
    lines.append(f"마지막 질문: {question}")

    schema = {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}
    response = _chat(
        [{"role": "system", "content": REWRITE_RULES}, {"role": "user", "content": "\n".join(lines)}],
        format=schema,  # JSON 모양을 강제해서 작은 AI도 실수 없이 답하게 해요
        options={"num_predict": 60},
    )
    try:
        rewritten = " ".join(str(json.loads(response.message.content)["question"]).split())
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return question
    # 여러 문장을 쓰면 마지막 문장(질문)만 써요
    rewritten = re.split(r"(?<=[.!?])\s+", rewritten)[-1]
    # 안전장치: 지금 질문의 핵심 낱말이 바뀐 질문에 절반도 없으면 AI가 엉뚱하게 바꾼 거예요.
    # (예: 새 주제 "파이썬 리스트 정렬"을 앞 질문 "세종대왕은 언제 태어났어?"로 바꿔 버리는 경우)
    q_grams = _content_grams(question)
    if not rewritten or len(rewritten) > 100:
        return question
    if q_grams and len(q_grams & _keywords(rewritten)) / len(q_grams) < 0.5:
        return question
    return rewritten


# ---------------------------------------------------------------------------
# 2) 페이지에서 질문과 관련 있는 부분만 고르기
# ---------------------------------------------------------------------------

def _keywords(text: str) -> set[str]:
    """비교용 낱말 조각을 뽑아요.

    한국어는 '위성은', '위성의'처럼 뒤에 붙는 말이 바뀌어서 낱말 통째로 비교하기 어려워요.
    그래서 두 글자씩 잘라서(위성, 성은) 비교해요. 영어와 숫자는 낱말 통째로 비교해요.
    """
    grams = set()
    for word in re.findall(r"[가-힣]+|[a-z0-9]+", text.lower()):
        if word.isascii():
            if len(word) >= 2 or word.isdigit():
                grams.add(word)
        else:
            grams.update(word[i:i + 2] for i in range(len(word) - 1))
    return grams


def _split_chunks(text: str) -> list[str]:
    """본문을 CHUNK_CHARS 글자 안팎의 조각으로 잘라요. 줄바꿈은 그대로 둬요(표의 한 줄 = 한 정보)."""
    chunks, buf = [], ""
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if buf and len(buf) + len(line) > CHUNK_CHARS:
            chunks.append(buf)
            buf = ""
        buf = f"{buf}\n{line}".strip()
        while len(buf) > CHUNK_CHARS * 1.5:  # 한 줄이 너무 길면 잘라요
            chunks.append(buf[:CHUNK_CHARS])
            buf = buf[CHUNK_CHARS:]
    if buf:
        chunks.append(buf)
    return chunks


def select_context(question: str, page_text: str, budget: int) -> str:
    """페이지에서 질문과 관련 있는 조각을 골라 budget 글자 안으로 줄여요.

    question 에는 검색 결과 요약문을 함께 넣어 주면 좋아요. 질문은 "태어났어"인데
    페이지에는 "출생"이라고 적혀 있을 때, 요약문에 있는 "출생"이 둘을 이어 줘요.
    """
    chunks = _split_chunks(page_text)
    q = _keywords(question)
    chunk_grams = [q & _keywords(c) for c in chunks]
    # 낱말 조각마다 몇 개의 조각에 나오는지 세요.
    # 여러 조각에 다 나오는 말(예: 세종)은 덜 중요하고, 한두 조각에만 나오는 말(예: 출생)이 더 중요해요
    count = Counter(g for grams in chunk_grams for g in grams)

    def score(i: int) -> float:
        s = sum(1 / count[g] for g in chunk_grams[i])
        return s + (0.5 if i == 0 else 0)  # 첫 조각은 요약일 때가 많아서 조금 더 줘요

    scored = sorted(range(len(chunks)), key=lambda i: (score(i), -i), reverse=True)
    picked, used = [], 0
    for i in scored:
        if used + len(chunks[i]) > budget and picked:
            continue
        picked.append(i)
        used += len(chunks[i])
    # 원래 순서대로 이어 붙여야 글이 자연스러워요
    return "\n…\n".join(chunks[i] for i in sorted(picked))[:budget]


def build_contexts(question: str, pages: list[dict], hints: list[str] = ()) -> tuple[list[dict], dict[int, str]]:
    """페이지마다 AI에게 보여 줄 부분을 골라요.

    hints : 검색 결과 요약문 등. 관련 부분을 고를 때 질문과 함께 써요
    돌려주는 것: (출처 목록 [{"n", "title", "url"}], {자료 번호: 고른 글})
    """
    sources = [{"n": i, "title": p["title"], "url": p["url"]} for i, p in enumerate(pages, start=1)]
    if not pages:
        return sources, {}
    budget = CONTEXT_CHARS // len(pages)  # 자료마다 같은 양씩 나눠요
    look_for = " ".join([question, *hints])
    contexts = {s["n"]: select_context(look_for, p["text"], budget) for s, p in zip(sources, pages)}
    return sources, contexts


# ---------------------------------------------------------------------------
# 3) 근거 확인: AI가 지어낸 문장 걸러내기
# ---------------------------------------------------------------------------

# 어떤 글에나 흔히 나오는 조각(조사, 말끝, 질문하는 말)은 근거 확인에서 빼요
COMMON_GRAMS = {
    "으로", "에서", "에게", "에는", "에도", "하고", "하는", "하면", "하지", "지만", "해요", "어요",
    "아요", "예요", "이에", "에요", "니다", "습니", "합니", "있어", "있는", "있습", "없어", "되어",
    "돼요", "되고", "이고", "이며", "그리", "리고", "그래", "래서", "때문", "문에", "대한", "대해",
    "위해", "같은", "정도", "자료", "료에", "따르", "르면", "나와", "와요", "알려", "려줘", "려요",
    "무엇", "엇이", "엇으", "어떻", "떻게", "어떤", "개야", "뭐야", "인가", "인지", "까요", "나요",
    "세요", "주세", "줘요",
}
# 문장의 중요한 낱말 조각 중 이 비율 이상이 자료에 있어야 근거가 있다고 봐요
SUPPORT_RATIO = 0.5
# 질문의 핵심 낱말 조각이 자료에 이 비율도 없으면 AI를 부르지 않고 바로 "찾지 못했어요"
QUESTION_COVERAGE = 0.34
# "몇 개", "언제" 처럼 숫자로 답하는 질문인지 알아보는 말
NUMBER_WORDS = ("몇", "언제", "얼마", "년도", "연도", "높이", "길이", "크기", "무게", "인구", "나이", "날짜")


def _content_grams(text: str) -> set[str]:
    """흔한 조각을 뺀 '중요한' 낱말 조각만 남겨요."""
    return _keywords(text) - COMMON_GRAMS


def _numbers(text: str) -> set[str]:
    """글 속 숫자를 뽑아요. 1,500 → 1500 처럼 쉼표는 빼요."""
    return set(re.findall(r"\d+(?:\.\d+)?", text.replace(",", "")))


def _support(sentence: str, context: str) -> float:
    """문장이 자료(context)에 얼마나 근거가 있는지 0~1 점수로 알려 줘요."""
    body = re.sub(r"\[\d+\]", "", sentence)  # 출처 번호는 빼고 봐요
    # 숫자를 지어내는 게 가장 위험해서, 숫자가 하나라도 자료에 없으면 0점이에요
    if not _numbers(body) <= _numbers(context):
        return 0.0
    grams = _content_grams(body)
    if not grams:
        return 1.0  # 중요한 낱말이 없는 짧은 문장
    return len(grams & _keywords(context)) / len(grams)


def _split_sentences(answer: str) -> list[str]:
    """답을 문장으로 나눠요. '1.5스푼' 같은 소수점에서는 자르지 않아요."""
    found = re.findall(r"(?:[^.!?\n]|\.(?=\d))+[.!?]?(?:\s*\[\d+\])*", answer)
    return [s.strip() for s in found if s.strip()]


def check_grounding(answer: str, contexts: dict[int, str]) -> tuple[str, list[str]]:
    """답의 문장마다 자료에 근거가 있는지 확인해요.

    contexts : {자료 번호: AI에게 보여 준 글}
    - 근거가 있는 문장은 남겨요.
    - 출처 번호가 없거나 틀렸지만 다른 자료에 근거가 있으면, 번호를 그 자료로 고쳐요.
    - 어느 자료에도 근거가 없는 문장은 빼요.
    돌려주는 것: (고친 답, 뺀 문장 목록)
    """
    kept, dropped = [], []
    for sentence in _split_sentences(answer):
        if "찾지 못했" in sentence:
            continue  # "찾지 못했어요"는 근거가 필요 없어요. 남는 문장이 없으면 마지막에 다시 붙여요
        cited = [int(n) for n in re.findall(r"\[(\d+)\]", sentence)]
        if cited and _support(sentence, " ".join(contexts[n] for n in cited)) >= SUPPORT_RATIO:
            kept.append(sentence)
            continue
        # 근거가 가장 많은 자료를 찾아봐요
        best = max(contexts, key=lambda n: _support(sentence, contexts[n]))
        if _support(sentence, contexts[best]) >= SUPPORT_RATIO:
            body = re.sub(r"\s*\[\d+\]", "", sentence)
            end = re.search(r"[.!?]$", body)
            kept.append(f"{body[:-1]}[{best}]{body[-1]}" if end else f"{body}[{best}]")
        else:
            dropped.append(sentence)
    return " ".join(kept), dropped


def _covers_question(question: str, contexts: dict[int, str]) -> bool:
    """질문의 핵심 낱말이 자료에 충분히 있는지 확인해요."""
    q_grams = _content_grams(question)
    if not q_grams:
        return True
    all_grams = _keywords(" ".join(contexts.values()))
    return len(q_grams & all_grams) / len(q_grams) >= QUESTION_COVERAGE


# ---------------------------------------------------------------------------
# 4) 빠른 답: AI 없이 원문에서 관련 문장 고르기 (약 0.1초)
# ---------------------------------------------------------------------------

def _context_sentences(text: str) -> list[str]:
    """자료 글을 문장으로 나눠요. 표의 | 기호는 빈칸으로 바꿔요."""
    sentences = []
    for line in text.split("\n"):
        line = re.sub(r"\s*\|\s*", " ", line).replace("---", " ")
        for part in re.split(r"(?<=[.!?])\s+", line):
            part = " ".join(part.split())
            if 12 <= len(part) <= 220:  # 너무 짧거나 긴 문장은 빼요
                sentences.append(part)
    return sentences


def quick_answer(question: str, pages: list[dict], hints: list[str] = ()) -> dict | None:
    """AI 없이, 질문과 가장 관련 있는 원문 문장을 몇 개 골라요.

    원문을 그대로 보여 주는 거라 지어낼 수가 없어요. AI 정리가 끝나기 전에 먼저 보여 줘요.
    돌려주는 모양: {"quotes": [{"n": 자료 번호, "text": 원문 문장}], "sources": [...]}
    관련 문장이 없으면 None
    """
    sources, contexts = build_contexts(question, pages, hints)
    if not contexts or not _covers_question(question, contexts):
        return None

    q = _content_grams(question)
    wants_number = any(word in question for word in NUMBER_WORDS)
    candidates = [(n, s) for n, text in contexts.items() for s in _context_sentences(text)]
    grams = [q & _keywords(s) for _, s in candidates]
    count = Counter(g for gs in grams for g in gs)  # 드물게 나오는 낱말일수록 중요해요

    def score(i: int) -> float:
        s = sum(1 / count[g] for g in grams[i])
        if wants_number and re.search(r"\d", candidates[i][1]):
            s += 0.5  # 숫자를 묻는 질문이면 숫자가 있는 문장이 좋아요
        return s

    order = sorted((i for i in range(len(candidates)) if grams[i]), key=score, reverse=True)
    quotes, per_source = [], Counter()
    for i in order:
        n, text = candidates[i]
        if per_source[n] >= 2 or any(text == q_["text"] for q_ in quotes):
            continue  # 한 자료에서 너무 많이 가져오지 않아요
        quotes.append({"n": n, "text": text})
        per_source[n] += 1
        if len(quotes) >= QUICK_SENTENCES:
            break
    return {"quotes": quotes, "sources": sources} if quotes else None


# ---------------------------------------------------------------------------
# 5) AI가 답 쓰기
# ---------------------------------------------------------------------------

def _clean_citations(answer: str, n_sources: int) -> str:
    """출처 번호를 정리해요.

    [자료 1] → [1], [1, 2] → [1][2] 로 바꾸고, 없는 자료 번호(예: 자료가 3개인데 [5])는 지워요.
    """
    def fix(match):
        nums = [int(x) for x in re.findall(r"\d+", match.group(0))]
        return "".join(f"[{x}]" for x in nums if 1 <= x <= n_sources)

    return re.sub(r"\[(?:자료\s*)?\d+(?:\s*,\s*(?:자료\s*)?\d+)*\]", fix, answer)


def write_answer(question: str, pages: list[dict], hints: list[str] = (), on_token=None) -> dict:
    """읽은 페이지들을 보고 출처 번호가 붙은 답을 써요.

    pages    : [{"title", "url", "text"}, ...]  (reader.read_results 결과)
    hints    : 검색 결과 요약문 등. 페이지에서 관련 부분을 고를 때 질문과 함께 써요
    on_token : 글자가 만들어질 때마다 불러 줄 함수 (화면에 바로바로 보여 줄 때 써요)
    돌려주는 모양: {"answer": 답, "sources": [{"n", "title", "url"}], "cited": [쓴 번호들],
                   "dropped": [근거가 없어서 뺀 문장들], "stats": {...}}
    """
    for kind, value in stream_answer(question, pages, hints):
        if kind == "token" and on_token:
            on_token(value)
        elif kind == "result":
            return value


def stream_answer(question: str, pages: list[dict], hints: list[str] = ()):
    """write_answer 와 같은 일을 하지만, 진행 상황을 하나씩 내보내요.

    ("token", 글자 조각) 을 여러 번 내보내고, 마지막에 ("result", 결과) 를 내보내요.
    웹 화면처럼 '쓰는 중'을 바로바로 보여 줘야 할 때 써요.
    """
    sources, contexts = build_contexts(question, pages, hints)
    not_found = {"answer": NOT_FOUND, "sources": sources, "cited": [], "dropped": [], "stats": {}}
    # 질문의 핵심 낱말이 자료에 거의 없으면, AI를 부르지 않고 바로 "찾지 못했어요" (1분 가까이 아껴요)
    if not contexts or not _covers_question(question, contexts):
        yield "result", not_found
        return

    blocks = [f"[자료 {s['n']}] {s['title']}\n{contexts[s['n']]}" for s in sources]
    # 질문을 자료 앞에 먼저 보여 주고, 끝에 한 번 더 적어요 (작은 AI가 덜 잊어버려요)
    user_msg = f"[질문] {question}\n\n" + "\n\n".join(blocks) + f"\n\n[질문] {question}\n답:"

    stream = _chat(
        [{"role": "system", "content": ANSWER_RULES}, {"role": "user", "content": user_msg}],
        stream=True,
        options={"num_predict": MAX_ANSWER_TOKENS},
    )
    parts, last = [], None
    try:
        for chunk in stream:
            piece = chunk.message.content or ""
            parts.append(piece)
            last = chunk  # 마지막 조각에 '얼마나 읽고 썼는지' 기록이 들어 있어요
            yield "token", piece
    except (ConnectionError, ollama.ResponseError) as e:
        # 조금씩 받는 방식(stream)에서는 오류가 받는 도중에 나요
        raise _friendly_error(e) from e

    answer = _clean_citations("".join(parts).strip(), len(sources))
    # "2023 년 3 월" → "2023년 3월" 처럼 숫자와 단위 사이 빈칸을 붙여요
    answer = re.sub(r"(\d) (?=[년월일개명%위배억만천시분초])", r"\1", answer)
    # 문장마다 자료에 근거가 있는지 확인하고, 지어낸 문장은 빼요
    answer, dropped = check_grounding(answer, contexts)
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)})
    # 속도 확인용 기록: AI가 읽은 양(토큰)과 쓴 양, 각각 걸린 시간(초)
    stats = {}
    if last is not None and last.prompt_eval_count:
        stats = {
            "read_tokens": last.prompt_eval_count,
            "read_sec": round((last.prompt_eval_duration or 0) / 1e9, 1),
            "write_tokens": last.eval_count,
            "write_sec": round((last.eval_duration or 0) / 1e9, 1),
        }
    yield "result", {
        "answer": answer or NOT_FOUND,
        "sources": sources,
        "cited": cited,
        "dropped": dropped,
        "stats": stats,
    }


if __name__ == "__main__":
    import time

    from reader import read_results
    from search import SearchError, search

    question = " ".join(sys.argv[1:]) or input("질문: ").strip()
    if not question:
        sys.exit("질문이 비어 있어요.")

    try:
        warm_up()
        t0 = time.monotonic()
        pages = read_results(search(question, max_results=8), want=3)
        hints = [p["snippet"] for p in pages]
        print(f"페이지 {len(pages)}개 읽음 ({time.monotonic() - t0:.1f}초)\n")

        quick = quick_answer(question, pages, hints)
        print("[빠른 답 - 원문 문장]")
        for quote in (quick or {}).get("quotes", []):
            print(f"  \"{quote['text']}\" [{quote['n']}]")

        print("\nAI가 정리하는 중", end="", flush=True)
        t0 = time.monotonic()
        result = write_answer(question, pages, hints, on_token=lambda t: print(".", end="", flush=True))
        print(f" ({time.monotonic() - t0:.1f}초, {result['stats']})\n")
    except (BrainError, SearchError) as e:
        sys.exit(str(e))

    print(result["answer"])
    if result["dropped"]:
        print(f"\n(자료에서 근거를 찾지 못한 문장 {len(result['dropped'])}개는 뺐어요)")
    print("\n출처:")
    for s in result["sources"]:
        mark = "" if s["n"] in result["cited"] else "  (답에 안 쓰임)"
        print(f"[{s['n']}] {s['title']}\n    {s['url']}{mark}")
