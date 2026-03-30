# 연구실 IP 등록 관리 Discord 봇

연구실 공용 대역의 IP를 Discord 슬래시 커맨드로 등록·관리하는 내부 도구입니다.
IP를 직접 입력하거나, 자동 감지 링크(웹 claim)를 통해 현재 접속 IP를 등록할 수 있습니다.

---

## 목차

1. [Discord 설정](#1-discord-설정)
2. [환경변수 설정](#2-환경변수-설정)
3. [실행 방법](#3-실행-방법)
4. [명령어](#4-명령어)
5. [IP 자동 감지 (Claim) 흐름](#5-ip-자동-감지-claim-흐름)
6. [트러블슈팅](#6-트러블슈팅)
7. [보안 고려사항](#7-보안-고려사항)

---

## 1. Discord 설정

### 1-1. 애플리케이션 생성

1. [Discord Developer Portal](https://discord.com/developers/applications) 접속
2. **New Application** → 이름 입력 (예: `LabIP Bot`) → **Create**

### 1-2. Bot 토큰 발급

1. 좌측 **Bot** 클릭
2. **Reset Token** → 토큰 복사 → `.env`의 `DISCORD_TOKEN`에 입력
3. **Message Content Intent**는 비활성화 유지 (슬래시 커맨드 전용)

### 1-3. 봇 초대 링크 생성

1. 좌측 **OAuth2 > URL Generator**
2. **Scopes**: `bot`, `applications.commands` 체크
3. **Bot Permissions**: `Send Messages`, `Embed Links`, `Attach Files` 체크
4. 생성된 URL로 봇을 서버에 초대

### 1-4. ID 확인 방법

Discord 설정 → 고급 → **개발자 모드** 활성화 후:

| 항목 | 확인 방법 |
|------|----------|
| Guild ID | 서버 이름 우클릭 → **ID 복사** |
| Channel ID | 채널 이름 우클릭 → **ID 복사** |
| Role ID | 서버 설정 → 역할 → 역할 우클릭 → **ID 복사** |

---

## 2. 환경변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열어 값을 채웁니다:

```env
# [필수] Discord 봇 토큰
DISCORD_TOKEN=your_bot_token_here

# 길드(서버) 설정 — 1개 이상 필수, 번호를 이어서 추가 가능
GUILD_1_ID=your_guild_id_here
GUILD_1_CHANNEL_ID=your_channel_id_here   # 비워두면 모든 채널에서 허용
GUILD_1_ROLE_ID=your_role_id_here         # 비워두면 역할 제한 없음

# GUILD_2_ID=...
# GUILD_2_CHANNEL_ID=...
# GUILD_2_ROLE_ID=...

# 등록 허용 IP 서브넷 앞 3옥텟 (예: 192.168.1)
IP_PREFIX=your_ip_prefix_here

# 웹서버 설정 (IP 자동 감지 엔드포인트)
WEB_HOST=127.0.0.1
WEB_PORT=8080
WEB_BASE_URL=http://localhost:8080      # Docker/NAT 환경에서는 실제 접근 가능한 주소로 변경

# Claim 토큰 유효 시간(초) — 기본값: 300 (5분)
TOKEN_TTL_SECONDS=300

# 데이터 파일 경로 (기본값 그대로 사용 권장)
IP_STATE_FILE=data/ip-state.json
TOKEN_FILE=data/ip-tokens.json

TZ=Asia/Seoul
```

> `.env` 파일은 절대 git에 커밋하지 마세요. `.gitignore`에 이미 포함되어 있습니다.

---

## 3. 실행 방법

### Docker Compose (권장)

```bash
# 프로젝트 디렉토리로 이동 후 실행
cd /path/to/labip

# 데이터 디렉토리 생성 (최초 1회)
mkdir -p data logs

# 이미지 빌드 및 시작
docker compose up -d --build

# 로그 확인
docker compose logs -f

# 중지
docker compose down
```

### 로컬 실행 (개발/테스트용)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# .env 로드 후 실행
export $(grep -v '^#' .env | xargs)
python -m app.main
```

---

## 4. 명령어

| 명령어 | 설명 | 권한 필요 |
|--------|------|-----------|
| `/register` | IP 등록. `ip` 생략 시 자동 감지 링크 발급 | 지정 역할 + 지정 채널 |
| `/release` | 등록된 IP 해제 | 지정 역할 + 지정 채널 |
| `/change` | 등록된 IP의 기기·사람 이름 수정 | 지정 역할 + 지정 채널 |
| `/status` | 현재 등록된 모든 IP 목록 확인 | 지정 역할 + 지정 채널 |
| `/help` | 사용법 안내 | 없음 |

**제약사항**:
- 지정된 Guild · Channel · Role 조건을 모두 만족해야 명령이 실행됩니다.
- `GUILD_N_CHANNEL_ID`, `GUILD_N_ROLE_ID`를 비워두면 각각의 제한이 해제됩니다.

### 명령어 예시

```
# IP 직접 지정해서 등록
/register ip:192.168.1.100 device:랩탑 person:홍길동

# 현재 접속 IP 자동 감지 링크 발급 (ip 생략)
/register device:데스크탑 person:홍길동

# 등록된 IP 해제
/release ip:192.168.1.100

# 기기 이름만 수정
/change ip:192.168.1.100 device:새기기이름
```

---

## 5. IP 자동 감지 (Claim) 흐름

1. `/register`에서 `ip`를 생략하면 일회용 Claim 링크가 발급됩니다.
2. 링크 버튼을 클릭하면 브라우저에서 `GET /ip/claim?token=...` 요청이 전송됩니다.
3. 서버가 요청자의 클라이언트 IP를 감지하고 허용 대역 여부를 검증합니다.
4. 검증 통과 시 IP가 자동 등록되고 결과 페이지가 표시됩니다.

**주의사항**:
- 링크는 `TOKEN_TTL_SECONDS`(기본 5분) 후 만료됩니다.
- 한 번 사용한 링크는 재사용할 수 없습니다.
- 리버스 프록시 환경에서는 `X-Real-IP` 또는 `X-Forwarded-For` 헤더를 신뢰합니다.
- 연구실 네트워크(`IP_PREFIX` 대역) 외부에서 접속하면 등록이 거부됩니다.

---

## 6. 트러블슈팅

### Bind mount 실패: 디렉토리가 없음

```
Bind mount failed: '/path/to/data' does not exist
```

docker-compose.yml이 있는 디렉토리에서 실행하거나, 볼륨 경로를 직접 생성하세요:

```bash
mkdir -p data logs
docker compose up -d
```

### 슬래시 커맨드가 보이지 않음

- 봇 로그 확인: `docker compose logs labip-bot`
- `슬래시 커맨드 동기화: N개 → guild=...` 로그가 출력되어야 정상
- 길드 스코프 동기화는 보통 수 초 내 반영됩니다. 최대 1분 대기 후 Discord 재시작

### 명령 실행 시 "이 채널에서는 사용할 수 없습니다"

- `GUILD_1_CHANNEL_ID`가 현재 채널 ID와 일치하는지 확인
- 비워두면 모든 채널에서 허용됩니다

### Claim 링크 클릭 시 "허용되지 않는 IP 주소" 오류

- 연구실 네트워크에 접속된 상태인지 확인
- `IP_PREFIX` 환경변수가 올바른 서브넷 앞 3옥텟인지 확인

### 봇이 채널에 메시지를 보내지 못함

- 봇 초대 시 `Send Messages`, `Embed Links` 권한 확인
- `GUILD_1_CHANNEL_ID`가 올바른 텍스트 채널 ID인지 확인

---

## 7. 보안 고려사항

- 등록 가능한 IP는 `IP_PREFIX`로 지정된 서브넷(`x.x.x.1~254`)으로 제한됩니다.
- Claim 토큰은 일회용이며 만료 시간이 있습니다.
- Discord 토큰은 로그에 마스킹 처리됩니다.
- Guild · Channel · Role 세 가지 조건을 통해 명령 실행 권한을 제어합니다.
- 봇은 non-root 사용자로 실행됩니다.
