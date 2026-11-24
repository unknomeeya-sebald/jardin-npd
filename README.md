# NPD 일정·이력 관리 (PBL 2일차)

- `backend/` — Python FastAPI · SQLAlchemy · Supabase(Postgres). 연결 실패 시 `backend/local.db`(SQLite)로 대체하고 `/api/health`의 `db` 값에 표시
- `frontend/` — Next.js 16 · React 19 · Tailwind CSS 4

## 실행

```bash
# 백엔드 (http://localhost:8000, 문서 /docs)
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000

# 프런트엔드 (http://localhost:3000)
cd frontend
npm install
npm run dev
```

DB 접속 정보는 `backend/.env` (git 제외). `DB_FORCE_SQLITE=1`이면 SQLite만 쓴다.

## 로그인·회원가입

- 화면: `/login`, `/signup`. 로그인하지 않으면 모든 화면이 `/login?next=원래경로`로 이동하고, 로그인 후 원래 경로로 돌아간다
- 가입 제한: `ALLOWED_EMAIL_DOMAINS`(기본 `jardin.co.kr`, 쉼표로 여러 개, `*`이면 제한 없음)의 주소만 가입된다. 다른 도메인의 예외 주소는 `ALLOWED_EMAILS`에 적는다. 제한은 가입할 때만 보며 이미 가입한 계정의 로그인은 막지 않는다. 메일 주소의 실제 주인인지는 확인하지 않는다
- 비밀번호 찾기: `/forgot`. 이메일을 넣으면 6자리 인증 코드를 본인 Slack DM으로 보내고(10분 유효, 5회까지 입력, 60초 뒤 재전송), 코드와 새 비밀번호를 넣으면 바뀐 뒤 바로 로그인된다. Slack 봇에 `users:read.email` 권한이 있어야 하며, Slack 프로필 이메일이 가입 이메일과 같아야 한다
- API: `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/forgot`, `POST /api/auth/reset`, `GET /api/auth/me` (`backend/app/auth.py`). `/api/health`를 뺀 모든 API는 `Authorization: Bearer <토큰>` 필요
- 비밀번호는 8자 이상·영문+숫자, scrypt 해시로 `npd_users`에 저장. 토큰은 HMAC 서명, 기본 12시간(`AUTH_TOKEN_TTL_HOURS`)
- 서명 키 `AUTH_SECRET`은 `backend/.env`에 둔다. 없으면 기동할 때마다 임시 키가 생겨 재기동 시 다시 로그인해야 한다

## Slack 지연 알림

- 채널: `C0C093UBJ49`. `backend/.env`에 `SLACK_WEBHOOK_URL`(Incoming Webhook) 또는 `SLACK_BOT_TOKEN`(xoxb-, `chat:write` 권한, 봇을 채널에 초대)을 넣고 백엔드를 다시 켠다
- 보내는 경우: ① 빨강 Task(기한 지남·미완료, 지연 완료)가 새로 생길 때 Task마다 한 번 ② 지연 흡수 결과 출시일에 영향이 생길 때 한 번. 보낸 기록은 `npd_alert_log`
- 점검 시점: 서버가 `SLACK_CHECK_INTERVAL_MIN`(기본 60)분마다, 오늘 기준 일정 조회·실적 입력 때. 기준일을 바꿔 본 가정 조회는 보내지 않는다
- 화면 「판정·흡수 설정」에서 연결 상태 확인, 시험 발송, 지금 점검 (`backend/app/notify.py`)

## Action Item (Slack → LLM → DB)

- 화면 「모니터링 › Action Item」: Slack 채널 대화에서 할 일·담당자·기한·제품을 뽑아 `npd_action_items`에 저장하고, 상태(할 일/진행 중/완료)·담당·기한·제품을 바로 고친다
- LLM: Upstage Solar(`backend/app/llm.py`, OpenAI 호환 Chat Completions). `.env`의 `UPSTAGE_API_KEY`, `UPSTAGE_MODEL`(기본 `solar-pro4`)
- Slack 읽기: `SLACK_BOT_TOKEN`(xoxb-, `channels:history`·`users:read`, 봇을 채널에 초대) 필요. 웹훅으로는 읽을 수 없다. 마지막으로 읽은 메시지를 `npd_action_sync`에 남겨 다음에는 새 메시지만 읽는다. 봇 메시지(지연 알림)는 제외
- 봇 토큰이 없을 때는 「대화 붙여 넣기」로 복사한 대화·회의록에서 추출. 줄 앞 날짜(`[11/04 09:12]`)를 읽어 「이번주 금요일」 같은 기한을 그 날짜 기준으로 계산
- 같은 근거 메시지·같은 담당자 항목은 다시 저장하지 않는다. API: `GET /api/actions`, `POST /api/actions/extract/slack|text`, `PATCH|DELETE /api/actions/{id}`

## 시험 — 한 명령

```bash
cd backend
python -m pytest tests -v          # 전체 (역산·신호등·동시 진행·흡수 3건)
python -m app.tools.compare        # 1교시: 엔진 ↔ 엑셀 일치 표 (일치 수 / 어긋남 수 / 어긋난 Task 표)
```

`data/excel_expected.csv`(열: `launch_date,task_no,task_name,excel_start,excel_end`)에 엑셀 값을 옮겨 넣어야 1교시 비교가 돈다. 비어 있으면 「확인 필요」로 건너뛴다.

## 데이터

| 파일 | 내용 | 상태 |
|---|---|---|
| `data/tasks_seed.csv` | Task 39행 (`no,name,phase,start_offset,duration,basis,predecessors,buffer_days,note`) | 16개만 값 있음(회신 v08 부록 B, NEW\|표준). 23개 「확인 필요」 |
| `data/holidays.csv` | 2026–2027 공휴일 28건 | 엑셀 29건과 대조 필요, 공동연차 미입력 |

엑셀 39개 기준 데이터는 화면의 「엑셀·CSV 가져오기」(.xlsx·CSV) 또는 `POST /api/tasks/import`로 넣는다.

## 규칙 (엔진)

- 착수일 = 출시일 − 착수 역산일수(영업일), 종료일 = 출시일 − (착수 역산일수 − 소요일수)
- D-주차 = 역산 영업일수 ÷ 5 올림 (C-02)
- 공휴일 미등록 연도의 출시일은 제품 생성 거부 (C-05)
- 신호등: 초록 = 기한 내 완료 또는 남은 여유 > 기준값 / 노랑 = 남은 여유 ≤ 기준값 / 빨강 = 기한 지남·미완료 또는 지연 완료
- 지연 흡수(C-01): 출시일 고정, 늦은 Task 뒤 ~ 「흡수 한도 Task」까지 번호 순으로 여유에서 흡수, 남으면 출시일 영향(영업일·날짜)과 지연 알림. 의사코드는 `backend/app/engine/absorb.py` 머리말
