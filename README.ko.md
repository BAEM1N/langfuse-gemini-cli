# langfuse-gemini-cli

[English](README.md) | [한국어](README.ko.md)

[Gemini CLI](https://github.com/google-gemini/gemini-cli)의 대화를 [Langfuse](https://langfuse.com)에 자동으로 트레이싱합니다. 에이전트 턴, LLM 호출, 도구 실행, 세션 이벤트 등 모든 과정이 Langfuse 대시보드에 구조화된 트레이스로 기록됩니다 -- 코드 변경 없이 작동합니다.

## 상태 (2026년 2월 25일)

- ✅ 실제 Gemini CLI 세션 기준 훅 파이프라인 검증 완료
- ✅ 세션 라이프사이클/턴/도구 스팬/버퍼 흐름 검증 완료
- ✅ 저장소 정리 완료 (불필요 추적 파일 없음 확인)
- ✅ 최종 문서 동기화 기준 `v0.0.1` 릴리즈/태그 정리 완료
- ✅ 다음 연동 저장소와 정렬 완료:
  - `langfuse-oh-my-codex`
  - `langfuse-claude-code`
  - `langfuse-opencode`
- 진행 문서: [English](./PROGRESS.md) | [한국어](./PROGRESS.ko.md)

## 주요 기능

- **전체 이벤트 커버리지** -- Gemini CLI의 11개 hook 이벤트 전체 캡처
- **턴 단위 트레이싱** -- 사용자 프롬프트 + 어시스턴트 응답이 Langfuse 트레이스로 기록
- **LLM 호출 추적** -- 모델 호출 전후의 요청, 응답, 토큰 사용량
- **도구 호출 추적** -- 도구 실행 전후의 입력, 출력, 소요 시간
- **도구 선택 캡처** -- 도구 필터링 및 선택 과정 기록
- **세션 라이프사이클** -- 세션 시작(startup/resume/clear) 및 종료(exit/logout) 이벤트
- **알림 캡처** -- 시스템 알림을 독립 이벤트로 기록
- **컨텍스트 압축** -- 압축 전 이벤트 추적
- **세션 그루핑** -- Gemini CLI 세션 ID로 트레이스 그룹화
- **버퍼 기반 조립** -- 턴 내 이벤트를 버퍼링하여 완성된 트레이스로 조립
- **Fail-open 설계** -- 오류 발생 시 조용히 종료; Gemini CLI에 영향 없음
- **크로스 플랫폼** -- macOS, Linux, Windows 지원
- **Dual SDK 지원** -- langfuse `>= 3.12` (중첩 스팬) 및 이전 버전 (플랫 트레이스) 모두 지원

## 사전 요구사항

- **Gemini CLI** -- 설치 및 동작 확인 (`gemini --version`으로 확인)
- **Python 3.8+** -- `pip` 사용 가능 (`python3 -m pip --version` 또는 `python -m pip --version`으로 확인)
- **Langfuse 계정** -- [cloud.langfuse.com](https://cloud.langfuse.com) (무료 티어 사용 가능) 또는 셀프 호스팅 인스턴스

## 빠른 시작

```bash
# 클론 후 설치 스크립트 실행
git clone https://github.com/BAEM1N/langfuse-gemini-cli.git
cd langfuse-gemini-cli
bash install.sh
```

Windows (PowerShell):

```powershell
git clone https://github.com/BAEM1N/langfuse-gemini-cli.git
cd langfuse-gemini-cli
.\install.ps1
```

설치 스크립트가 수행하는 작업:
1. Python 3.8+ 확인
2. `langfuse` 파이썬 패키지 설치
3. Hook 스크립트를 `~/.gemini/hooks/`에 복사
4. Langfuse 인증 정보 입력
5. 11개 hook 이벤트를 `~/.gemini/settings.json`에 등록
6. 설치 검증

## 수동 설치

### 1. langfuse SDK 설치

```bash
pip install langfuse
```

### 2. Hook 스크립트 복사

```bash
mkdir -p ~/.gemini/hooks ~/.gemini/state
cp langfuse_hook.py ~/.gemini/hooks/
chmod +x ~/.gemini/hooks/langfuse_hook.py
```

### 3. `~/.gemini/settings.json` 설정

설정 파일에 다음 내용을 추가(또는 병합)하세요:

```json
{
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
    "BeforeAgent": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
    "BeforeModel": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
    "BeforeToolSelection": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
    "AfterModel": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
    "BeforeTool": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
    "AfterTool": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
    "AfterAgent": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
    "Notification": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
    "PreCompress": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
    "SessionEnd": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}]
  },
  "env": {
    "TRACE_TO_LANGFUSE": "true",
    "LANGFUSE_PUBLIC_KEY": "pk-lf-...",
    "LANGFUSE_SECRET_KEY": "sk-lf-...",
    "LANGFUSE_BASE_URL": "https://cloud.langfuse.com",
    "LANGFUSE_USER_ID": "your-username"
  }
}
```

## 설정

### 환경변수

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `TRACE_TO_LANGFUSE` | Yes | - | `"true"`로 설정하여 트레이싱 활성화 |
| `LANGFUSE_PUBLIC_KEY` | Yes | - | Langfuse public key (`GC_LANGFUSE_PUBLIC_KEY` 우선) |
| `LANGFUSE_SECRET_KEY` | Yes | - | Langfuse secret key (`GC_LANGFUSE_SECRET_KEY` 우선) |
| `LANGFUSE_BASE_URL` | No | `https://cloud.langfuse.com` | Langfuse 호스트 URL (`GC_LANGFUSE_BASE_URL` 우선) |
| `LANGFUSE_USER_ID` | No | `gemini-user` | 트레이스 귀속 사용자 ID (`GC_LANGFUSE_USER_ID` 우선) |
| `GC_LANGFUSE_DEBUG` | No | `false` | `"true"`로 설정하여 상세 로깅 활성화 |
| `GC_LANGFUSE_MAX_CHARS` | No | `20000` | 텍스트 필드 최대 문자 수 (초과 시 잘림) |

모든 `LANGFUSE_*` 변수는 `GC_LANGFUSE_*` 접두사도 지원합니다 (접두사 버전 우선).

### 셀프 호스팅 Langfuse

`LANGFUSE_BASE_URL`을 인스턴스 URL로 설정:

```json
"LANGFUSE_BASE_URL": "https://langfuse.your-company.com"
```

## 작동 원리

```
┌──────────────────────────────────────────────────────────────┐
│                       Gemini CLI                              │
│                                                               │
│  사용자 입력 ──► 모델 호출 ──► 도구 실행 ──► 응답              │
│       │              │              │              │           │
│       ▼              ▼              ▼              ▼           │
│  BeforeAgent    BeforeModel    BeforeTool    AfterAgent        │
│       │         AfterModel     AfterTool         │            │
│       │              │              │              │           │
│       └──────────────┴──────┬───────┘              │           │
│                             │                      │           │
│                     ┌───────▼───────┐    ┌────────▼────────┐  │
│                     │ 버퍼 (JSONL)   │    │ 트레이스 조립    │  │
│                     └───────────────┘    └────────┬─────────┘ │
│                                                   │           │
│  SessionStart ──┐                                 │           │
│  Notification ──┤ (독립 이벤트)                    │           │
│  PreCompress ───┤                                 │           │
│  SessionEnd ────┘                                 │           │
└───────────────────────────────────────────────────┼───────────┘
                                                    │
                                                    ▼
                                          ┌─────────────────────┐
                                          │      Langfuse        │
                                          │                      │
                                          │  Trace (Turn 1)      │
                                          │  ├─ Agent Request     │
                                          │  ├─ LLM Call [1]      │
                                          │  │   ├─ model         │
                                          │  │   ├─ usage tokens  │
                                          │  │   └─ response      │
                                          │  ├─ Tool Selection    │
                                          │  ├─ Tool: read_file   │
                                          │  ├─ LLM Call [2]      │
                                          │  ├─ Tool: write_file  │
                                          │  └─ Agent Response    │
                                          │                      │
                                          │  Event: SessionStart  │
                                          │  Event: Notification  │
                                          │  Event: SessionEnd    │
                                          │                      │
                                          │  Session: abc123      │
                                          └─────────────────────┘
```

**흐름:**

1. Gemini CLI가 에이전트 루프의 각 단계에서 hook 이벤트를 발생시킴
2. **버퍼 이벤트** (`BeforeAgent`, `BeforeModel`, `AfterModel`, `BeforeToolSelection`, `BeforeTool`, `AfterTool`)는 JSONL 버퍼 파일에 축적
3. **AfterAgent** 발생 시 (턴 완성) 버퍼를 읽어 완전한 트레이스로 조립하여 Langfuse에 전송
4. **독립 이벤트** (`SessionStart`, `SessionEnd`, `Notification`, `PreCompress`)는 즉시 전송
5. 각 턴 트레이스에 포함되는 항목:
   - **Agent Request** 스팬 (BeforeAgent의 사용자 프롬프트)
   - **LLM Call** 제너레이션 관측 (AfterModel의 모델명, 토큰 사용량)
   - **Tool Selection** 스팬 (BeforeToolSelection의 도구 설정)
   - **Tool** 스팬 (BeforeTool/AfterTool 쌍의 입출력)
   - **Agent Response** 스팬 (AfterAgent의 최종 응답)
6. 모든 트레이스는 동일한 `session_id`로 그룹화

## Hook 이벤트 (전체 11개)

| 이벤트 | 타입 | 캡처 데이터 |
|--------|------|-------------|
| `SessionStart` | 독립 | 세션 소스 (startup/resume/clear) |
| `BeforeAgent` | 버퍼 | 사용자 프롬프트 |
| `BeforeModel` | 버퍼 | LLM 요청 |
| `BeforeToolSelection` | 버퍼 | 사용 가능 도구 설정 |
| `AfterModel` | 버퍼 | LLM 요청 + 응답 + 토큰 사용량 |
| `BeforeTool` | 버퍼 | 도구명 + 입력 |
| `AfterTool` | 버퍼 | 도구명 + 입력 + 응답 |
| `AfterAgent` | **트레이스 전송** | 프롬프트 + 응답 (버퍼 이벤트 조립) |
| `Notification` | 독립 | 알림 타입 + 메시지 |
| `PreCompress` | 독립 | 압축 트리거 |
| `SessionEnd` | Flush + 정리 | 종료 사유 + 잔여 버퍼 플러시 |

## 호환성

| 구성요소 | 버전 |
|---------|------|
| Python | 3.8+ |
| langfuse SDK | 2.0+ (플랫 트레이스), 3.12+ (중첩 스팬) |
| Gemini CLI | 0.26.0+ (hooks 지원) |
| OS | macOS, Linux, Windows |

## 문제 해결

### 트레이스가 표시되지 않을 때

1. settings에 `TRACE_TO_LANGFUSE`가 `"true"`로 설정되었는지 확인
2. API 키가 올바른지 확인
3. 디버그 로깅 활성화: `GC_LANGFUSE_DEBUG`를 `"true"`로 설정
4. 로그 파일 확인: `~/.gemini/state/langfuse_hook.log`

### Hook이 작동하지 않을 때

1. `~/.gemini/settings.json`에 11개 이벤트 키 모두에 hook이 등록되었는지 확인
2. 명령어의 Python 경로가 올바른지 확인 (`python3` vs `python`)
3. 수동 테스트: `echo '{"hook_event_name":"SessionStart","session_id":"test"}' | python3 ~/.gemini/hooks/langfuse_hook.py` (Windows에서는 `python3` 대신 `python` 사용)

### 중복 트레이스

턴 카운트가 `~/.gemini/state/langfuse_state.json`에 기록됩니다. 새로 시작하려면 이 파일을 삭제하세요.

### 텍스트 잘림

기본적으로 텍스트 필드는 20,000자에서 잘립니다. `GC_LANGFUSE_MAX_CHARS`로 조정:

```json
"GC_LANGFUSE_MAX_CHARS": "50000"
```

## 제거

1. `~/.gemini/settings.json`에서 모든 hook 항목 제거
2. Hook 스크립트 삭제: `rm ~/.gemini/hooks/langfuse_hook.py`
3. 선택적으로 상태 제거: `rm -rf ~/.gemini/state/langfuse_*`

## 라이선스

[MIT](LICENSE)
