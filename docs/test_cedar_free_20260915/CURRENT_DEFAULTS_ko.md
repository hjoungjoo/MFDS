# 현재 기본값과 비교 방법

2026-09-15. 개별 실험 문서의 당시 기본값과 이 문서가 다르면 이 문서를 따른다.
테스트 브랜치의 검증 구성을 main 기본값으로 채택했다.
[메인 확정 결정](../MAIN_FINALIZATION_ko.md)을 참고한다.

추가 현장 진단: [달 중앙·도심 조명 결과](MOON_CITY_DIAGNOSIS_RESULTS_ko.md).
정지 상태의 영역 제외+10프레임 누적은 유망한 비교안이며, 아래의 5프레임
런타임 기본값을 변경한 것은 아니다.

[토성 GoTo 후 추적 실측](SATURN_GOTO_RESULTS_ko.md): 현재 장면은 RAW MF4p와
전처리 MF4p가 유망했다. 기존 Cedar 운영 추적과 MF 오프라인 재생을 구분했으며,
MF 실시간 마운트 제어를 검증하거나 기본값·운영 서비스를 변경한 결과는 아니다.

| 영역 | 채택한 기본값 | 근거/비교 옵션 |
|---|---|---|
| 검출 | MF4p: 전체 1/4→후보 주변 1/2 | [다단계 실측](PYRAMID_RESULTS_ko.md), `mf2`, `mf1`, `mf4o`, `mf8p` 비교 |
| 후보 | sigma4.5, response 순서, 최대48개 | RAW/전처리에 같은 MF 적용, 원본 재측정 기본 끔 |
| SEP | MF 오류/필터 후 5개 미만 때 보조 | `mf4p-pure`는 SEP 끔, `sep`는 SEP 비교 |
| 실행 | 스레드별 독립 native MF 프로세스 + memfd, 실패 시 0.5~8초 재시도 대기 | [IPC 실측](PROCESS_RESULTS_ko.md), `ctypes`는 명시적 비교 |
| 전처리 | 전체 영상, CFA 보존, 배경 스케일3작업자, 시간 창5장 | 위치·기하 구조 유지 |
| 시간 누적 | 단일 프레임 후보 마스크와 가중 신호 재사용 | [직전 실측](PREPROCESS_PLACEMENT_RESULTS_ko.md), [통합 실측](INTEGRATED_OPTIMIZATION_RESULTS_ko.md) |
| 솔빙 | 개선 Tetra3 검색, RAW 3초/전처리 탐색 2.6초 공유 예산 + 기존 개별 제한 | [검색 실측](SPEED_RESULTS_ko.md), [검토 반영](REVIEW_FIX_RESULTS_ko.md), 후보 순서와 품질 기준 유지 |
| 스케줄 | auto: 안정적인 RAW는 비동기 전처리와 같은 노출 bias 보정 | RAW 실패·초기 안정화·정렬·보정은 같은 프레임 전처리 대기 유지 |
| 보정 수명 | 비동기 결과 제출 후 5초, 유효 보정 갱신 후 30초 | 만료 시 RAW 유지, 새 2개 표본으로 재안정화. 최신 대기 프레임 우선 |
| 관측 기록 | 관측/타겟 좌표·노출 시각·코드/실행 파일 해시·MF 커밋·의존성 버전 | `TETRA3_SEARCH_OPTIMIZED` 환경 설정도 기록 |

항상 전처리 anchor, 전처리/검출 통합 Python 프로세스, 원본 해상도 재측정,
1/8 탐색은 비교 대상으로 남긴다. 특정 자료의 중앙값만으로 기본으로 승격하지
않았다. 현재 auto는 항상 전처리 좌표를 주 좌표로 발행하는 anchor와 다르다.
[anchor 비교](ANCHOR_RESULTS_ko.md), [실행 위치 비교](PREPROCESS_PLACEMENT_RESULTS_ko.md).

## 메모리와 숫자 결과

가중 신호는 양자화된 신호 배열을 대체한다. 새 시간 누적 배열을 추가하지 않는다.
1080×1920/5장 기준 신호 float32 + evidence float32 + 후보 마스크 bool의
유지 메모리는 약 89MiB/누적기다. 두 누적기 기준 약 178MiB이며 이전 버전과 같다.
전체 프로세스 RSS에는 배경 계산 임시 배열, Python/SciPy, MF, 솔버 DB 등이
추가되므로 이 값을 전체 메모리 사용량으로 해석하면 안 된다.

시간 창에서 프레임을 제거하거나 reset하면 대응 배열 참조도 제거한다.
가중치 계산 시점만 이동하며 원래 half→float 양자화, 각 프레임 연산 및 합산
순서는 보존한다. 후보 성분의 면적 범위와 연결 규칙도 같다.
속도를 위해 별 개수·검사 범위·정확도 기준을 낮추지 않는다.

## 설정과 전환

`PiFinder.detector_profiles.runtime_environment()`가 실행 기본값을 함께 만든다.
`profile_environment()`/`configure_profile()`는 검출기만 선택하므로 비교 도구가
명시한 transport나 이전 검색 옵션을 덮어쓰지 않는다.

```bash
# 설정을 출력하기만 한다. 서비스를 변경하지 않는다.
PYTHONPATH=python python3 -m PiFinder.detector_profiles --runtime --systemd

# 사용자가 서비스 전환을 요청한 경우에만 실행한다.
sudo scripts/test_runtime.sh start mf4p auto process
sudo scripts/test_runtime.sh start mf2 auto process
sudo scripts/test_runtime.sh start mf4p sync process
sudo scripts/test_runtime.sh start mf4p auto ctypes
sudo scripts/test_runtime.sh restore
```

전환은 `/run` override이며 부팅 기본 소스를 바꾸지 않는다. 이번 작업에서
이 start/restore 명령은 실행하지 않았다. 스위치는 개선 검색을 명시적으로
선택하므로 이전 실험의 검색 환경 변수를 우연히 상속하지 않는다.

수치 비교와 재현 명령은 [통합 실측 결과](INTEGRATED_OPTIMIZATION_RESULTS_ko.md),
전체 현장 절차는 [FIELD_GUIDE](FIELD_GUIDE_ko.md)에 있다.

## 달·도심 장면 노출 비교

[중앙 하단 달 노출 실측](MOON_LOWER_EXPOSURE_RESULTS_ko.md)은 별도 기록 376장과
재생 비교 결과다. 이 고정 장면에서는 하늘 영역 제외, 낮은 gain/긴 노출,
RAW MF2의 전체 영역 우선 탐색과 MF4p 전처리 주 좌표가 유망했다.
수동 마스크·특정 장면의 결과이며 기본 프로파일과 서비스는 변경하지 않았다.
달이 사라진 후의 자료는 노출 비교 자료와 분리했다.
