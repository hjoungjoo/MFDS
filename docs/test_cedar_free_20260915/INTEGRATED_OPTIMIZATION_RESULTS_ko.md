# 재부팅 후 누적 개선 통합 결과

2026-09-15. [사전 계획](INTEGRATED_OPTIMIZATION_PLAN_ko.md),
[현재 기본값](CURRENT_DEFAULTS_ko.md), [좌표 없는 집계](integrated_optimization.summary.json).

**MF4p + 독립 MF 프로세스 + auto 전처리 + 개선 검색을 유지하고,
전처리의 가중 신호 재사용과 후보 성분 조회 최적화를 추가했다.**
누적 배열의 유지 메모리를 늘리지 않고 같은 수치 결과를 얻는다.
전처리 포함 처리 중앙값은 직전 버전 대비 약 3% 추가 감소했다.
병렬 RAW와 실제 auto의 모든 지연 지표가 감소한 것은 아니다.

## 변경과 기준 버전

기준은 MF `da9743a`의 전처리다. 직전 작업의 단일 프레임 후보 마스크 캐시가
이미 포함되어 있다. 개선 구현과 비교 도구는 `f4d9e51`이다.
재부팅 전의 절대 시간과 이번 시간을 빼서 개선율을 계산하지 않는다.

- **가중 신호 재사용:** float16→float32 양자화 뒤 각 프레임의 support를 한 번
  계산해 신호 배열에 적용한다. 과거 프레임의 나눗셈/clip/곱셈을 매번 반복하지
  않는다. 새로운 누적 배열을 추가하지 않고, 프레임 합산 순서를 유지한다.
- **성분 조회:** 연결 성분의 크기로 bool 허용 표를 만들고 label 번호로 직접
  조회한다. 성분 번호 목록과 전체 영상 membership 검사가 불필요해졌다.
  8방향 연결 및 면적 최소/최대 경계는 유지한다.
- **실행 기본값 통합:** `runtime_environment()`가 MF4p, auto, process,
  `TETRA3_SEARCH_OPTIMIZED=1`을 함께 만든다. 서비스 전환 도구가 이 값을 쓴다.
  검출기만 바꾸는 기존 비교 API는 transport/search override를 보존한다.
- **기록:** 기존 관측/목표 좌표 저장에 더해 검색 최적화 환경 변수도 기록한다.
- **재생 도구:** auto 비교에서 이전 전처리 파일을 명시할 수 있고 RAW SHA256을
  검증한다. 시간 창 식별자는 실제 정책처럼 노출/게인 대신 geometry와 generation을
  사용한다. 따라서 이전 문서의 재생과 절대 수치를 직접 이어 붙이지 않는다.

라이선스 범위나 native IPC/검출 알고리즘, 솔빙 품질 기준, RAW 실패/정렬/보정
대기 정책은 변경하지 않았다. C++ 전처리 이식이나 서비스 배포 작업이 아니다.

## 같은 입력의 전처리·검출·솔빙

고정 광해 검증 처음 20장과 구름 19번째부터 20장, 각각 2회 실행했다.
같은 프로세스의 같은 실행에서 이전/개선 순서를 교대한다.
배경 작업자3개, 누적5장, MF4p/process, 개선 검색을 공통으로 사용한다.
각 반복 첫4장을 제외하여 데이터/방식별 16장×2회=32회다.
검증용 evidence 해시/출력 취득 비용도 측정에 포함된다.

단위 ms, p50 / p95. 캐시 영상을 재사용한 검출만의 시간이 아니라
RAW에서 전처리를 실제 계산한 시간이다.

| 자료 | 이전 전체 | 개선 전체 | 중앙값 감소 | 전처리만 p50 이전→개선 |
|---|---:|---:|---:|---:|
| 고정 광해 검증 | 1026.0 / 1236.8 | **990.1 / 1216.7** | **3.5%** | 970.2→940.4 |
| 구름 | 1015.0 / 1193.9 | **983.6 / 1154.5** | **3.1%** | 974.7→943.7 |

이전/개선 모두 각각32/32 솔빙 성공이다. 단일 프레임 마스크 캐시를 처음 넣었을
때의 약10–11% 개선에 더한 비교지만, 서로 다른 실행의 개선율을 단순 합산하지
않는다. 여기서는 두 추가 최적화를 함께 측정했으며 각각의 기여를 분리하지 않았다.

## RAW 병렬 부하

각 자료12장×2회, 첫4장 제외, 방식별16회. 전처리가 동작하는 동안 같은 RAW를
최대10Hz로 반복 검출한다. 100ms를 넘으면 직전 검출이 끝나야 다음 호출한다.
전처리 완료 시 반복을 멈추므로 호출 수가 다르며, 고정 시간의 전체 RAW 지연이나
실제 GOTO 지연이 아니다. RAW 솔빙/카메라/SQM/UI는 이 부하 시험에 없다.

| 자료 | 전체 p50 이전→개선 | 전체 p95 이전→개선 | RAW p50 이전→개선 | RAW p95 이전→개선 | RAW 호출 이전→개선 |
|---|---:|---:|---:|---:|---:|
| 검증 | 1132.5→1159.3 | 1414.5→1364.2 | 38.0→40.3 | 73.8→78.7 | 192→193 |
| 구름 | 1332.2→1278.9 | 1602.6→1490.4 | 122.7→115.8 | 183.7→197.2 | 169→166 |

RAW p95는 검증 약5ms, 구름 약13ms 늘었다. 사용자가 직전의 작은 RAW 지연을
허용한 방향에 따라 전처리 개선을 테스트 기본에 반영했지만, 이번 증가량까지
별도 측정해 숨기지 않는다. 전처리 처리량 개선을 RAW 응답성 개선으로 표현하지
않는다. RAW/전처리 경합과 반복별 변동이 있으므로 모든 조건의 속도 향상은 아니다.

전처리 비교와 병렬 비교 합계 **256회 처리(기준128회+비교128회)**에서
영상 픽셀/evidence/검출 좌표/밝기/진단이 정확히 같다. 집계 구간 전처리 솔빙
**192회 모두 성공**, 좌표/RMSE/매칭 수/경로도 기준과 같다. SEP 호출0회다.
RMSE는 카탈로그 매칭 잔차이며 마운드 절대 지향 오차 측정이 아니다.

## 실제 auto 정책 재생

자료별24장, 이전/개선 각각 별도 프로세스 한 번씩 재생했다. 검증은 이전→개선,
구름은 개선→이전 순서다. 실제 전처리, LatestFrameWorker, 스케줄 정책, bias,
continuity gate를 사용한다. 노출 입력 간격은 최소0.4초이며 처리 지연으로
더 길어질 수 있다. 카메라 IPC, SQM, UI, 실제 마운드는 포함하지 않는다.

| 경로 | p50 이전→개선(ms) | p95 이전→개선(ms) | 좌표 채택 이전→개선 |
|---|---:|---:|---:|
| 검증 정상 비동기 foreground 22회 | 112.3→126.4 | 1024.8→1019.2 | 22/24→22/24 |
| 검증 완료된 background 전처리+검출 | 1117.1→1072.8 | 1300.0→1179.8 | — |
| 구름 동일 프레임 동기 복구24회 | 1614.2→1523.0 | 2268.6→2396.2 | 18/24→18/24 |

검증 RAW24/24 성공, 초기sync2회/async22회, bias 갱신7회씩이다.
구름 RAW0/24여서24회 모두 기존 동기 복구 정책을 따른다. SEP 호출은 모두0회다.
전처리 솔빙 성공과 품질/연속성 검사 후 좌표 채택은 다른 지표이며, 18/24를
위의 같은 입력 비교192/192 성공과 혼동하면 안 된다.

구름 복구 중앙값은5.7% 감소했으나 p95는약128ms 증가했다. 예를 들어
`raw_003`의 RAW 검출+실패 검색 자체가1288→1414ms로 달랐다. 이 행의
RAW 검출 코드는 변경하지 않았으며, 시간 제한이 있는 검색과 실행 부하도
합계에 포함된다. 단일 재생으로 증가 원인을 확정하거나 최악 지연을 보장하지
않는다. **이번 결과는 전체 지연의 모든 백분위가 개선됐다는 증거가 아니다.**

## 메모리·검증·운영 범위

추가 시간 누적 배열은 없다. 1080×1920/5장 유지 배열은 양쪽 모두
93,312,000bytes(약89MiB)/누적기, 2개면 약178MiB다. 전체 RSS와 다르다.
단위 테스트에서 시간 창을 초과한 입력 뒤 유지 용량을 검사하고, reset 후
배열 weak reference가 해제되는 것도 확인했다. 실행 중 확인한 스왑 사용량은0이었다.
장기간 서비스 운용의 메모리 누수 부재를 입증하는 시험은 아니다.

- 전체 unit: **2372 passed, 2 skipped**, 기존 경고8개.
- 관련 전처리/프로필/스케줄/연결 테스트54개 통과.
- native6/6, Ruff, 변경 Python format, shell syntax, 라이선스 범위/diff 검사 통과.
- smoke7개, MyPy205파일 통과. 검사 종료 후 swap0, available4798MiB였으며
  테스트 MF worker가 남아 있지 않음을 확인했다.
- 재부팅 후 운영 PiFinder PID714/Cedar PID704 및 기존 경로를 확인했다.
  테스트 서비스로 전환하거나 부팅·카메라·마운드 설정을 변경하지 않았다.
- 소스·문서·집계는 두 승인된 테스트 브랜치에 저장한다. 상세 결과와 관측 좌표는
  로컬 `PiFinder_test_data/results/integrated_*.json`에 유지한다.

## 재현

기준 파일을 별도 저장하고 PiFinder 테스트 Python 환경에서 실행한다.
기존 출력 파일을 덮어쓰지 않는다.

```bash
git -C /home/pifinder/mf_detect_star_test show da9743a:integrations/pifinder/PiFinder/mf_star_only_preprocess.py > /home/pifinder/PiFinder_test_data/work/integrated_optimization/reference.py
cd /home/pifinder/PiFinder_test/python
PIFINDER_DATA_DIR=/home/pifinder/PiFinder_test_data PYTHONPATH=.:scripts \
  /home/pifinder/PiFinder/python/.nox/unit_tests/bin/python \
  scripts/benchmark_preprocess_placement.py CORPUS CACHE NEW_RESULT.json \
  --reference /home/pifinder/PiFinder_test_data/work/integrated_optimization/reference.py \
  --implementation PiFinder/mf_star_only_preprocess.py \
  --frames 20 --repeats 2 --modes current,current_cached
```

구름은 `--start 18`을 추가한다. 병렬 부하는 `--frames 12 --repeats 2 --raw-probe`,
구름에 `--wide`를 추가한다. 이 도구의 `current`가 직전 기준,
`current_cached`가 이번 가중 신호/성분 조회 개선을 뜻한다.

auto 재현은 `benchmark_auto_detector.py CORPUS CACHE NEW_RESULT.json --mode mf4p
--frames 24 --preprocess-source SOURCE.py`를 쓴다. 이전/개선 전처리 파일을 각각
명시하고 구름에만 `--wide`를 준다. 비교 때 공통으로
`MF_DETECT_TRANSPORT=process TETRA3_SEARCH_OPTIMIZED=1`을 사용한다.
