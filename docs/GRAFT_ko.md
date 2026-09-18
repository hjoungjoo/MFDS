# Graft 개발 도구

[Graft](https://github.com/trailhq/Graft) 0.18.0으로 이 저장소의 코드 구조를 로컬에서 검색합니다.
이 장비에는 Node.js 22.23.2와 Graft가 `~/.local` 아래 설치되어 있습니다.

## 사용

```bash
export PATH="$HOME/.local/bin:$PATH"
export DO_NOT_TRACK=1
cd ~/MFDS
graft map
graft ask "detect_stars" --source
graft skeleton src/detector.cpp
graft check
```

`graft ask`는 순위 기반 검색이므로 결과의 실제 파일·심볼을 확인합니다.
정확한 문자열의 전체 출현 위치는 `graft grep` 또는 `rg`로 확인합니다.

`graft build`로 재구축할 수 있으며, 검색 명령도 변경된 코드의 구조를 자동 갱신합니다.
기본 구조 분석은 API 키나 LLM 호출이 필요 없습니다. `--deep` 요약은 별도의
모델 설정이 필요하며 이번 설치에서는 활성화하지 않았습니다.

## 에이전트 연동

- Codex: 루트 `AGENTS.md`의 Graft 안내에 따라 CLI로 탐색합니다.
- Claude Code: `.claude/`의 스킬·훅·상태 표시와 `.mcp.json`의 MCP 서버를 사용합니다.
  `~/.local/bin`이 PATH에 포함된 환경에서 새 세션을 열어 적용합니다.
- `--no-global`로 초기화하여 저장소별 설정을 사용합니다.
- `graft/`는 `.gitignore`에 등록된 재생성 가능한 로컬 캐시입니다.

## 다른 장비에서 재현

Node.js 22와 npm을 준비한 뒤 저장소 루트에서 실행합니다.

```bash
npm install -g @nanonets/graft@0.18.0
DO_NOT_TRACK=1 graft telemetry disable
DO_NOT_TRACK=1 graft init --agents agents claude --no-global
DO_NOT_TRACK=1 graft check
```

Python 가상환경이나 MFDS 실행 바이너리와 별도로 설치되는 개발 도구입니다.

텔레메트리는 이 장비에서 `graft telemetry disable`로 영구 비활성화했습니다.
이 설정은 사용자별 로컬 설정이므로 다른 장비에서도 위 명령을 실행합니다.
