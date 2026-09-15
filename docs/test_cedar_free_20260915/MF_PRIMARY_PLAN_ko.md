# MF 우선 RAW/전처리 비교 — 작업 전 계획

사용자 수정 반영: 평상시 RAW가 안정적이면 기존 auto 스케줄로 백그라운드 전처리/검출을 수행하고, RAW 실패·초기 확인·정렬·왜곡/렌즈 보정 중에는 기존 동기 전처리 예외를 유지한다. 전처리 내부의3개 scale worker 설정도 유지한다. 운영 소스/서비스/부팅은 전환하지 않는다.

코드 확인: auto는 RAW3연속 성공 후 async, RAW 실패/강제동기/연속 continuity 거절 시 sync로 돌아간다. async 완료 결과는 제출 당시 동일 RAW 솔브와 비교하며 최대0.12도, 최소2표본, alpha0.25 bias를 최신 RAW에 적용한다. 이전 프레임 좌표를 최신 프레임 좌표로 대체하지 않는다. 현재 백그라운드 범위는 전처리+검출이고 완료된 후보의 Tetra3 솔빙은 메인 루프에서 처리한다.

추가 확인: solver_preprocess_skip_slow_raw_fallbacks=true와 전처리 trusted 상태는 auto 모드에서도 RAW solve를 건너뛸 수 있다. Cedar 제거 후 RAW가 이 fallback tier만 사용하므로 auto가 안정적인 RAW를 재확인하지 못할 수 있다. 이 최적화는 명시적 sync 모드에만 한정하여 요청된 평상시 RAW 흐름을 보장한다. 그 외 동기/비동기 전환 계약을 바꾸지 않는다.

검출 정책: MF 우선, 기존 필터 후 유효 후보5개 미만 또는 native 실행 오류일 때만 SEP를1회 호출한다. 후보가 충분하지만 Tetra3 솔빙에 실패한 경우는 SEP 재검출 조건에 포함하지 않는다. RAW와 전처리 영상에 같은 MF 방식/threshold/순서를 사용한다. 비교 대상은 MF2, MF4→2 ROI, MF4→2→1 ROI이며 SEP 호출수/실제 선택 backend를 분리 기록한다.

개발은 current 처음30장, 후속 평가 validation119장 및 cloud 평가102장. RAW와 동일한 캐시 전처리 영상에 같은 검출기와 기하/품질 게이트를 적용한다. 시간은 검출/솔브 분리, 전처리 공통 비용 별도, RAW 실패 시 전처리 복구 가능수를 기록한다. 실제 auto 모드의 동시 처리 성능은 관련 경계 테스트 및 녹화 프레임 비동기 재생으로 추가 확인한다. 검출 정책과 frame/continuity/bias/GOTO 검사, lint/mypy 및 필요 전체 검사를 완료해 승인된 두 테스트 브랜치에 단계별 푸시한다.
