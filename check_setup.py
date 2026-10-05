r"""
준비가 잘 됐는지 하나씩 확인하는 점검 프로그램이에요.

실행 (이 컴퓨터의 Ollama 쓰기):
    .venv\Scripts\python.exe check_setup.py

실행 (Ollama 클라우드 쓰기, 서버에 올리기 전에 확인):
    $env:OLLAMA_API_KEY = "여기에 내 API 키"
    .venv\Scripts\python.exe check_setup.py
"""

import sys
from importlib import metadata

# 클라우드 무료 플랜에서 쓸 수 있는지 시험해 볼 모델 후보 (모두 상업적으로 써도 되는 Apache 2.0)
CLOUD_CANDIDATES = ["gemma4:31b", "gpt-oss:20b", "gpt-oss:120b"]
# 이 컴퓨터의 Ollama가 켜져 있으면 이 주소에서 대답해요
OLLAMA_URL = "http://localhost:11434"


def check_python():
    """파이썬 버전이 3.10 이상인지 봐요."""
    v = sys.version_info
    ok = v >= (3, 10)
    print(f"[{'완료' if ok else '필요'}] 파이썬 {v.major}.{v.minor}.{v.micro}")
    return ok


def check_packages():
    """requirements.txt에 적은 패키지가 다 깔렸는지 봐요."""
    all_ok = True
    for name in ["ddgs", "trafilatura", "requests", "ollama", "protego", "flask"]:
        try:
            print(f"[완료] 패키지 {name} {metadata.version(name)}")
        except metadata.PackageNotFoundError:
            print(f"[필요] 패키지 {name} 이(가) 없어요 -> pip install -r requirements.txt")
            all_ok = False
    return all_ok


def check_local_ollama(model: str):
    """이 컴퓨터의 Ollama 프로그램이 켜져 있는지, 모델을 받아 뒀는지 봐요."""
    import requests

    try:
        # /api/tags 는 "내 컴퓨터에 받아 둔 모델 목록"을 알려줘요
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        r.raise_for_status()
    except requests.RequestException:
        print("[필요] Ollama가 꺼져 있거나 설치되지 않았어요 (README의 'Ollama 설치' 참고)")
        return False

    print("[완료] Ollama가 켜져 있어요")
    names = [m["name"] for m in r.json().get("models", [])]
    if model in names:
        print(f"[완료] 모델 {model} 준비됨")
        return True
    print(f"[필요] 모델 {model} 이(가) 없어요 -> ollama pull {model}")
    if names:
        print(f"       (지금 있는 모델: {', '.join(names)})")
    return False


def _cloud_answers(brain, model: str) -> str | None:
    """클라우드 모델에 아주 짧게 물어봐요. 되면 None, 안 되면 이유를 돌려줘요."""
    brain.MODEL, brain._thinking_supported = model, None
    try:
        brain._chat([{"role": "user", "content": "안녕이라고만 답해"}], options={"num_predict": 5})
        return None
    except brain.BrainError as e:
        return str(e)


def check_cloud_ollama(brain):
    """Ollama 클라우드에 연결되는지, 설정한 모델을 무료로 쓸 수 있는지 봐요."""
    print(f"[정보] Ollama 클라우드 모드예요 (모델: {brain.MODEL})")
    configured = brain.MODEL
    problem = _cloud_answers(brain, configured)
    if problem is None:
        print(f"[완료] 클라우드 모델 {configured} 이(가) 대답해요")
        return True
    print(f"[필요] 클라우드 모델 {configured} 을(를) 쓸 수 없어요: {problem}")

    # 다른 후보 중에 무료 플랜에서 되는 모델을 찾아 알려 줘요
    working = [m for m in CLOUD_CANDIDATES if m != configured and _cloud_answers(brain, m) is None]
    if working:
        print(f"       대신 쓸 수 있는 모델: {', '.join(working)}")
        print(f"       -> 환경 변수 SSAYUZ_MODEL 을 {working[0]} 로 바꿔 주세요 (Render 에서는 Environment 메뉴)")
    else:
        print("       후보 모델도 모두 안 돼요. API 키와 https://ollama.com/settings 의 사용량을 확인해 주세요.")
    return False


if __name__ == "__main__":
    print("=== ssayuz AI 준비 점검 ===")
    results = [check_python(), check_packages()]
    try:
        import brain
    except ImportError:
        brain = None  # 패키지가 아직 안 깔렸으면 brain.py 를 못 불러와요
    if brain is None:
        results.append(False)
    elif brain.CLOUD:
        results.append(check_cloud_ollama(brain))
    else:
        results.append(check_local_ollama(brain.MODEL))
    print()
    if all(results):
        print("모두 준비됐어요!")
    else:
        print("[필요] 라고 적힌 것만 해결하면 돼요.")
