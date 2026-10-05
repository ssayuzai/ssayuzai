# ssayuz AI 인터넷 서버에 올리기

노트북을 켜 두지 않아도, 카드 없이, 무료로 ssayuz AI를 인터넷 주소로 쓰는 방법이에요.

```
화면 + 파이썬(검색, 읽기, 로그인) → Render 무료 서버
AI 정리                           → Ollama 클라우드 무료 플랜
코드 보관                          → GitHub (비공개 저장소)
```

> **지금은 1단계(시험판)예요.** 서버에서 DuckDuckGo 검색이 되는지부터 확인해요.
> 시험판은 회원과 대화 기록을 서버 안에 저장해서, **서버가 잠들거나 다시 켜지면 지워져요.**
> 검색이 잘 되면 2단계에서 Neon(무료 DB)을 연결해서 지워지지 않게 할게요.

---

## 1. Ollama 클라우드 API 키 만들기

1. https://ollama.com 에서 **Sign up**으로 가입해요. (무료 플랜, 카드 필요 없음)
2. 로그인한 다음 https://ollama.com/settings/keys 로 가서 **Add API Key**를 눌러요.
3. 이름은 `ssayuz`처럼 아무거나 쓰고, 만들어진 키를 **복사해서 메모장에 잠깐 붙여 둬요.**

> ⚠️ API 키는 비밀번호와 같아요. 다른 사람에게 보여 주거나 GitHub, 카톡 등에 올리지 마세요.
> 실수로 보여 줬다면 같은 화면에서 그 키를 지우고 새로 만들면 돼요.

### (추천) 내 노트북에서 키가 되는지 먼저 확인하기

이 폴더에서 PowerShell을 열고 실행해요. `여기에_키`는 복사한 키로 바꿔요.

```powershell
$env:OLLAMA_API_KEY = "여기에_키"
.\.venv\Scripts\python.exe check_setup.py
```

- `[완료] 클라우드 모델 gemma4:31b 이(가) 대답해요` 가 나오면 성공이에요.
- `대신 쓸 수 있는 모델: ...` 이 나오면 그 **모델 이름을 메모**해 두세요. 5단계에서 써요.
- PowerShell 창을 닫으면 키는 사라져요. 노트북에 저장되지 않아요.

## 2. GitHub에 코드 올리기

1. https://github.com 에서 가입해요. (무료, 카드 필요 없음)
2. 오른쪽 위 **+** → **New repository**를 눌러요.
   - Repository name: `ssayuzai`
   - **Private**(비공개)를 선택해요.
   - 아래의 "Add a README file" 같은 체크는 **모두 비워 둬요.**
   - **Create repository**를 눌러요.
3. 이 폴더에서 PowerShell을 열고 차례대로 실행해요. (이미 연결해 뒀다면 두 번째 줄만 실행해요)

```powershell
git remote add origin https://github.com/ssayuzai/ssayuzai.git
```

```powershell
git push -u origin main
```

4. 브라우저 창이 뜨면 GitHub에 로그인해서 허락해 줘요. 끝나면 GitHub 저장소 화면을 새로 고침해서 파일들이 보이는지 확인해요.

> `.venv`(파이썬 상자)와 `data`(회원, 기록, 비밀 열쇠) 폴더는 `.gitignore` 때문에 올라가지 않아요.

## 3. Render에 서버 만들기

1. https://render.com 에서 **Get Started** → **GitHub로 가입**해요. (무료 플랜, 카드 필요 없음)
2. 오른쪽 위 **New +** → **Blueprint**를 눌러요.
3. GitHub 연결을 허락하고 `ssayuzai` 저장소를 골라요. Render가 `render.yaml`을 읽어요.
4. 값을 넣으라는 칸이 두 개 나와요.

| 칸 | 넣을 값 |
|---|---|
| `OLLAMA_API_KEY` | 1단계에서 복사한 API 키 |
| `SSAYUZ_INVITE_CODE` | **내가 정하는 초대 코드** (예: 길고 맞히기 어려운 말). 이걸 아는 사람만 가입할 수 있어요 |

5. **Apply**(또는 Deploy)를 누르고 5~10분 기다려요.
6. 서비스 화면 위쪽의 `https://ssayuz-ai-○○○○.onrender.com` 주소를 눌러요.

### 결제 정보를 물어보면

Blueprint 방식이 결제 정보를 요구하면 멈추고, 대신 **New +** → **Web Service**로 직접 만들어요.

| 설정 | 값 |
|---|---|
| Repository | `ssayuzai` |
| Language | Python 3 |
| Region | Singapore |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180` |
| Instance Type | **Free** |
| Health Check Path (Advanced) | `/healthz` |

**Environment Variables**에는 아래를 넣어요.

| Key | Value |
|---|---|
| `PYTHON_VERSION` | `3.12.10` |
| `SSAYUZ_HTTPS` | `1` |
| `SSAYUZ_MODEL` | `gemma4:31b` (1단계에서 다른 모델을 메모했으면 그 이름) |
| `SSAYUZ_READ_DEADLINE` | `12` |
| `SECRET_KEY` | **Generate** 단추로 무작위 값 만들기 |
| `OLLAMA_API_KEY` | API 키 |
| `SSAYUZ_INVITE_CODE` | 내가 정한 초대 코드 |

## 4. 시험하기

1. 주소로 들어가서 **회원가입** 탭에서 아이디, 비밀번호, **초대 코드**를 넣어요.
2. "세종대왕은 언제 태어났어?"처럼 물어봐요.
3. 결과를 알려 주세요. 특히 이 두 가지가 중요해요.
   - **검색이 되는지:** "DuckDuckGo가 잠시 검색을 막았어요"가 계속 나오면 서버에서 검색이 막힌 거예요.
   - **걸린 시간:** 원문 문장과 AI 정리가 각각 몇 초 만에 나오는지

## 서버에서 DuckDuckGo 검색이 안 될 때

Render 같은 데이터센터 서버에서는 DuckDuckGo 연결이 막힐 수 있어요.

1. 로그인한 상태에서 `https://내주소.onrender.com/api/diagnose/search` 를 열면, 서버에서 DuckDuckGo 연결을 단계별로 시험한 결과가 나와요.
2. 검색이 계속 안 되면 Render의 **Environment**에 아래 값을 추가하면, DuckDuckGo 대신 **Ollama 웹 검색**(공식 API, 같은 API 키 사용)으로 찾아요.

| Key | Value |
|---|---|
| `SSAYUZ_SEARCH_FALLBACK` | `ollama` |

> Ollama 웹 검색에는 DuckDuckGo 같은 세이프서치 설정이 없어요. 대신 성인 사이트 주소 거르기는 그대로 해요.

## 5. 모델 바꾸기, 설정 바꾸기

Render 서비스 화면 → **Environment** → 값을 바꾸고 **Save Changes**를 누르면 서버가 다시 켜져요.

## 알아둘 점

- **잠들기:** 15분 동안 아무도 접속하지 않으면 서버가 잠들어요. 다음 접속은 깨어나는 데 약 1분 걸려요.
- **무료 사용량:** Render는 한 달에 750시간까지 무료예요(서버 1개면 충분해요). Ollama 클라우드 무료 사용량은 https://ollama.com/settings 에서 볼 수 있고, 다 쓰면 다음 달에 다시 채워져요.
- **시험판의 기록:** 지금은 서버가 잠들거나 다시 켜지면 회원과 대화 기록이 지워져요. 2단계(Neon 연결)에서 해결해요.
- **코드를 고친 뒤 다시 올리기:** `git add -A`, `git commit -m "설명"`, `git push`를 하면 Render가 알아서 새 코드로 다시 켜요.

## 문제가 생기면

| 화면에 나온 말 | 해결 방법 |
|---|---|
| Ollama 클라우드 API 키가 맞지 않거나… | Render의 `OLLAMA_API_KEY` 값을 확인해요 |
| Ollama 클라우드에 '…' 모델이 없어요 | 1단계 점검으로 되는 모델을 찾아서 `SSAYUZ_MODEL`을 바꿔요 |
| 무료 사용량을 다 썼거나… | 다음 달까지 기다리거나 잠시 뒤에 다시 해요 |
| DuckDuckGo가 잠시 검색을 막았어요 | 1~2분 뒤에 다시 해 보고, 계속되면 알려 주세요 |
| 초대 코드가 맞지 않아요 | Render의 `SSAYUZ_INVITE_CODE` 값과 같은지 확인해요 |
