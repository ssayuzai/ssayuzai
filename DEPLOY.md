# ssayuz AI 인터넷 서버에 올리기

노트북을 켜 두지 않아도, 카드 없이, 무료로 ssayuz AI를 인터넷 주소로 쓰는 방법이에요.

```
화면 + 파이썬(검색, 읽기, 로그인) → Render 무료 서버
AI 정리 (+ 예비 웹 검색)           → Ollama 클라우드 무료 플랜
회원, 대화 기록                    → Neon 무료 DB (Postgres)
코드 보관                          → GitHub (비공개 저장소)
```

> 6단계(Neon 연결)까지 해야 **회원과 대화 기록이 지워지지 않아요.**
> Neon을 연결하기 전에는 서버 안에 임시로 저장해서, 서버가 잠들거나 다시 켜지면 지워져요.

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
4. 값을 넣으라는 칸이 나와요.

| 칸 | 넣을 값 |
|---|---|
| `OLLAMA_API_KEY` | 1단계에서 복사한 API 키 |
| `DATABASE_URL` | 6단계(Neon)를 한 뒤에 넣어요. 처음에는 비워 둬도 돼요 |

> **회원가입은 누구나 할 수 있어요.** 아는 사람만 가입하게 하려면 Environment에 `SSAYUZ_INVITE_CODE`(내가 정한 초대 코드)를 추가하면 돼요.

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
| `SSAYUZ_SEARCH_FALLBACK` | `ollama` |
| `SECRET_KEY` | **Generate** 단추로 무작위 값 만들기 |
| `OLLAMA_API_KEY` | API 키 |
| `SSAYUZ_INVITE_CODE` | (선택) 넣으면 이 코드를 아는 사람만 가입해요 |
| `DATABASE_URL` | 6단계에서 넣어요 |

## 4. 시험하기

1. 주소로 들어가서 **회원가입** 탭에서 아이디와 비밀번호를 넣어요. (초대 코드를 설정했으면 그것도)
2. "세종대왕은 언제 태어났어?"처럼 물어봐요.
3. 진행 단계에 `결과 8개 (Ollama 웹 검색)`처럼 나오면, DuckDuckGo가 서버에서 막혀서 예비 검색으로 찾은 거예요. 정상이에요.

## 5. 서버 검색 (DuckDuckGo + 예비 검색)

Render 같은 데이터센터 서버에서는 DuckDuckGo 연결이 막힐 수 있어요(실제로 시간 초과가 났어요).
그래서 `SSAYUZ_SEARCH_FALLBACK=ollama`로 **예비 검색**을 켜 뒀어요.

- DuckDuckGo를 먼저 시도하고, 안 되면 **Ollama 웹 검색**(공식 API, 같은 API 키 사용)으로 찾아요.
- 한 번 DuckDuckGo가 안 되면 10분 동안은 기다리지 않고 바로 예비 검색을 써요.
- Ollama 웹 검색은 페이지 본문도 함께 줘서, 작은 무료 서버가 페이지를 다시 받지 않아도 돼요.

> Ollama 웹 검색에는 DuckDuckGo 같은 세이프서치 설정이 없어요. 대신 성인 사이트 주소 거르기는 그대로 해요.
> Render 의 **Environment**에 `SSAYUZ_SEARCH_FALLBACK` 이 `ollama` 로 들어가 있는지 한 번 확인해 주세요. 없으면 직접 추가해요.

## 6. Neon DB 연결하기 (회원, 기록 저장)

1. https://neon.com 에서 **Sign up** → **GitHub로 가입**해요. (무료 플랜. 카드를 물어보면 멈추고 알려 주세요)
2. 새 프로젝트를 만들어요.
   - Project name: `ssayuz`
   - Postgres version: 기본값 그대로
   - **Region: AWS Asia Pacific (Singapore)** ← Render 서버와 같은 지역이라 빨라요
3. 프로젝트 화면의 **Connect** 단추를 누르고, **Connection string**(`postgresql://`로 시작하는 긴 주소)을 복사해요.
   - 이 주소 안에 **DB 비밀번호가 들어 있어요.** API 키처럼 남에게 보여 주거나 GitHub에 올리지 마세요.
4. Render 서비스 화면 → **Environment** → **Add Environment Variable**
   - Key: `DATABASE_URL`
   - Value: 복사한 주소
   - **Save Changes**를 누르면 서버가 다시 켜져요(약 3분).
5. 다시 켜지면 **마지막으로 한 번 더 회원가입**해요. 이제부터는 서버가 잠들거나 다시 켜져도 계정과 기록이 남아요.

> 표(테이블)는 서버가 켜질 때 자동으로 만들어져요. Neon에서 따로 할 일은 없어요.

## 7. 모델 바꾸기, 설정 바꾸기

Render 서비스 화면 → **Environment** → 값을 바꾸고 **Save Changes**를 누르면 서버가 다시 켜져요.

## 알아둘 점

- **잠들기:** 15분 동안 아무도 접속하지 않으면 서버가 잠들어요. 다음 접속은 깨어나는 데 약 1분 걸려요. Neon DB도 5분 동안 안 쓰면 잠들었다가, 다음에 쓸 때 1초 안팎으로 깨어나요.
- **무료 사용량:** Render는 한 달에 750시간까지 무료예요(서버 1개면 충분해요). Ollama 클라우드 무료 사용량은 https://ollama.com/settings 에서 볼 수 있고, 다 쓰면 다음 달에 다시 채워져요. Neon 무료 플랜은 프로젝트당 저장 공간 1GB예요.
- **코드를 고친 뒤 다시 올리기:** `git add -A`, `git commit -m "설명"`, `git push`를 하면 Render가 알아서 새 코드로 다시 켜요.

## 문제가 생기면

| 화면에 나온 말 | 해결 방법 |
|---|---|
| Ollama 클라우드 API 키가 맞지 않거나… | Render의 `OLLAMA_API_KEY` 값을 확인해요 |
| Ollama 클라우드에 '…' 모델이 없어요 | 1단계 점검으로 되는 모델을 찾아서 `SSAYUZ_MODEL`을 바꿔요 |
| 무료 사용량을 다 썼거나… | 다음 달까지 기다리거나 잠시 뒤에 다시 해요 |
| DuckDuckGo가 잠시 검색을 막았어요 / 검색 중 문제가 생겼어요 | `SSAYUZ_SEARCH_FALLBACK`이 `ollama`인지 확인해요 (5단계) |
| 예비 검색(Ollama)도 실패했어요 | Ollama 무료 사용량과 `OLLAMA_API_KEY`를 확인해요 |
| 초대 코드가 맞지 않아요 | Render의 `SSAYUZ_INVITE_CODE` 값과 같은지 확인해요 |
| 화면이 안 뜨고 Render Logs에 `pg8000`, `DATABASE_URL` 오류 | Neon 주소를 빠짐없이 복사했는지 확인해요 (`postgresql://`로 시작) |
