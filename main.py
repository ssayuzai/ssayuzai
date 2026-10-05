r"""
ssayuz AI 터미널 버전이에요. 질문을 처리하는 순서(run)는 웹 화면(app.py)도 함께 써요.

  (이어지는 질문이면) 이전 대화를 보고 질문 이해하기
  → 검색 → 페이지 동시에 읽기 → 빠른 답(원문 문장) → AI 정리

실행: .venv\Scripts\python.exe main.py                     (계속 묻고 답하기)
      .venv\Scripts\python.exe main.py 목성의 위성은 몇 개야   (한 번만 묻기)
끝내기: '종료'라고 쓰거나 Ctrl+C
"""

import sys
import threading
import time

import brain
from brain import BrainError
from reader import read_results
from search import SearchError, search

# 검색 결과를 몇 개 받을지 (이 중 위쪽 몇 개를 동시에 읽어요)
RESULTS_TO_SEARCH = 8
# AI에게 보여 줄 페이지 수 (많을수록 정확하지만 AI가 읽는 시간이 늘어요)
PAGES_TO_READ = 3
# 이 말을 쓰면 프로그램을 끝내요
QUIT_WORDS = {"종료", "끝", "exit", "quit", "q"}


def run(question: str, history: list[dict] = ()):
    """질문 하나를 끝까지 처리하면서, 진행 상황을 하나씩 내보내요.

    history : 같은 대화의 이전 질문과 답 [{"question", "answer"}, ...] (오래된 것부터)
    터미널(main.py)과 웹 화면(app.py)이 똑같은 순서로 일하도록 여기에 한 번만 적어 둬요.
    내보내는 것 (모두 사전 모양이라 웹으로 보내기도 쉬워요):
      {"type": "step", "text": 지금 하는 일}
      {"type": "done", "note": 결과 설명, "sec": 걸린 초}
      {"type": "understood", "question": 이해한 질문}   ← 이어지는 질문일 때만
      {"type": "quick", "quick": 빠른 답}              ← 원문에서 고른 문장
      {"type": "token"}                                 ← AI가 글자 조각을 하나 썼어요
      {"type": "result", "result": AI 정리, "question": 이해한 질문, "sec": 전체 걸린 초}
    """
    total = time.monotonic()

    # 1) 이어지는 질문("그럼 토성은?")이면 이전 대화를 보고 완전한 질문으로 바꿔요
    understood = question
    if history:
        t = time.monotonic()
        yield {"type": "step", "text": "이전 대화 살펴보는 중"}
        understood = brain.rewrite_question(question, list(history))
        yield {"type": "done", "note": understood, "sec": time.monotonic() - t}
        yield {"type": "understood", "question": understood}

    # 2) 검색은 한 번만 해요 (DuckDuckGo는 짧은 시간에 여러 번 검색하면 막아요)
    t = time.monotonic()
    yield {"type": "step", "text": "검색하는 중"}
    results = search(understood.rstrip("?!. "), max_results=RESULTS_TO_SEARCH)
    # 어느 검색엔진으로 찾았는지도 보여 줘요
    engine = {"ollama": "Ollama 웹 검색", "duckduckgo": "DuckDuckGo"}.get(results[0].get("engine"), "") if results else ""
    note = f"결과 {len(results)}개" + (f" ({engine})" if engine else "")
    yield {"type": "done", "note": note, "sec": time.monotonic() - t}

    # 3) 위쪽 페이지들을 동시에 읽어요 (최대 7초)
    t = time.monotonic()
    yield {"type": "step", "text": "페이지 읽는 중"}
    pages = read_results(results, want=PAGES_TO_READ)
    yield {"type": "done", "note": f"{len(pages)}개 읽음", "sec": time.monotonic() - t}

    # 검색 결과 요약문은 "태어났어" ↔ "출생" 처럼 다른 말을 이어 주는 힌트로 써요
    hints = [p["snippet"] for p in pages]

    # 4) AI 없이 원문에서 관련 문장을 골라 먼저 보여 줘요 (빠른 답)
    quick = brain.quick_answer(understood, pages, hints)
    if quick:
        yield {"type": "quick", "quick": quick, "sec": time.monotonic() - total}

    # 5) AI가 정리해서 답을 써요
    t = time.monotonic()
    yield {"type": "step", "text": "AI가 정리하는 중"}
    result = None
    for kind, value in brain.stream_answer(understood, pages, hints):
        if kind == "token":
            yield {"type": "token"}
        else:
            result = value
    yield {"type": "done", "note": "", "sec": time.monotonic() - t}

    yield {"type": "result", "result": result, "question": understood, "sec": time.monotonic() - total}


def _seconds(sec: float) -> str:
    """걸린 시간을 '1분 5초'처럼 읽기 쉽게 바꿔요."""
    m, s = divmod(round(sec), 60)
    return f"{m}분 {s}초" if m else f"{s}초"


def ask(question: str, history: list[dict] = ()) -> dict:
    """질문 하나를 처리하면서 터미널에 진행 상황과 답을 보여 줘요. 이번 질문과 답을 돌려줘요."""
    result, understood, total = None, question, 0.0
    for event in run(question, history):
        kind = event["type"]
        if kind == "step":
            print(f"  · {event['text']} ", end="", flush=True)
        elif kind == "token":
            print(".", end="", flush=True)  # 점을 찍어서 멈춘 게 아니라는 걸 보여 줘요
        elif kind == "done":
            note = f"→ {event['note']} " if event["note"] else " "
            print(f"{note}({_seconds(event['sec'])})")
        elif kind == "quick":
            print(f"\n[빠른 답 - 원문 문장, {_seconds(event['sec'])}]")
            for quote in event["quick"]["quotes"]:
                print(f"  \"{quote['text']}\" [{quote['n']}]")
            print()
        elif kind == "result":
            result, understood, total = event["result"], event["question"], event["sec"]

    print(f"\n[AI 정리]\n{result['answer']}\n")
    if result["cited"]:
        print("출처")
        for s in result["sources"]:
            if s["n"] in result["cited"]:
                print(f"  [{s['n']}] {s['title']}\n      {s['url']}")
    elif result["sources"]:
        # 답을 못 찾았을 때는 읽어 본 페이지를 보여 줘서 직접 확인할 수 있게 해요
        print("읽어 본 페이지")
        for s in result["sources"]:
            print(f"  - {s['title']}\n    {s['url']}")
    if result["dropped"]:
        print(f"\n(자료에서 근거를 찾지 못한 문장 {len(result['dropped'])}개는 뺐어요)")
    print(f"\n(걸린 시간 {_seconds(total)})")
    return {"question": understood, "answer": result["answer"]}


def main() -> None:
    # 질문을 입력하는 동안 AI 모델을 미리 불러 둬요 (처음 한 번 약 20초)
    threading.Thread(target=brain.warm_up, daemon=True).start()

    # 명령어 뒤에 질문을 적으면 한 번만 답하고 끝내요
    if len(sys.argv) > 1:
        try:
            ask(" ".join(sys.argv[1:]))
        except (SearchError, BrainError) as e:
            sys.exit(str(e))
        return

    print("ssayuz AI - 인터넷을 검색해서 출처와 함께 답해 드려요.")
    print("'그럼 토성은?'처럼 이어서 물어봐도 돼요. 새 주제로 바꾸려면 '새 대화'라고 쓰세요.")
    print("끝내려면 '종료'라고 쓰거나 Ctrl+C를 누르세요.")
    history = []  # 이번 대화의 질문과 답 (이어지는 질문을 이해할 때 써요)
    while True:
        try:
            question = input("\n질문> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            continue
        if question.lower() in QUIT_WORDS:
            break
        if question == "새 대화":
            history = []
            print("새 대화를 시작해요.")
            continue
        try:
            history.append(ask(question, history))
        except (SearchError, BrainError) as e:
            print(f"\n{e}")
        except KeyboardInterrupt:
            print("\n(이번 질문은 멈췄어요)")
    print("\n안녕히 가세요!")


if __name__ == "__main__":
    main()
