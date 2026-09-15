# MF 우선 검출과 RAW/전처리 실행 — 최종 결과

## 결론

테스트 기본 검출기를 **MF 전체1/4 탐색 → 후보 주변1/2 정밀화(mf4p)**로 선택했다. RAW와 전처리 영상에 같은 검출 방식, sigma4.5, response 순서, 최대48개를 적용한다. 필터 후 후보5개 미만 또는 native 실행 오류에서만 SEP를1회 보조 호출한다. MF 후보가 충분한 솔빙 실패는 기존 동기 전처리 복구로 이어지며 SEP 재검출을 하지 않는다. `PIFINDER_DETECTOR=sep`는 별도 비교용 수동 선택으로 남긴다.

사용자 수정대로 **RAW 실패·정렬·왜곡/렌즈 보정 중 메인 루프가 동일 프레임의 전처리를 기다리는 구조는 유지**했다. RAW3연속 성공 뒤 background로 전환하는 기존 auto 정책과 프레임/IMU anchor, continuity, bias 조건도 유지했다. 전처리 내부 배경 계산은 기본3개 worker이며 잘못된1-worker 설정이 들어와도 최소2개로 실행한다. 동기/백그라운드 처리기는 서로 다른 누적 버퍼와 scale executor를 갖는다.

코드에서 확인한 문제1개를 수정했다. 기존 `solver_preprocess_skip_slow_raw_fallbacks`는 전처리 trusted 뒤 auto에서도 RAW 솔브를 생략할 수 있었다. Cedar 제거 후 RAW가 그 tier를 사용하므로 RAW 안정성 확인과 async 복귀를 막을 수 있다. 이제 이 생략은 명시 sync 모드에서만 허용해 auto에서는 RAW 시도를 유지한다. `solver_scheduling.py`와 `preprocess_bias.py` 자체의 정책은 변경하지 않았다.

## 현재 동작 확인

자세한 흐름은 [MF_PRIMARY_FLOW_ko.md](MF_PRIMARY_FLOW_ko.md)에 정리했다.

1. 같은 노출의 RAW를 MF로 검출하고 기존 중심/전체 cascade로 솔빙한다.
2. 안정적인 RAW3연속 성공 후 전처리+검출을 latest-frame worker에서 처리한다. 평소 좌표는 RAW가 제공한다.
3. 완료된 전처리 후보의 **Tetra3 솔빙은 메인 루프에서 수행**한다. background인 것은 전처리와 검출이며 전체 솔버가 별도 스레드에 있는 것은 아니다.
4. 그 결과를 job에 보관한 **동일 노출의 RAW 솔브**와 비교한다. 기존 최대0.12도 일치 범위,2개 이상 표본,alpha0.25 조건으로 bias를 갱신하고 최신RAW에 적용한다. 과거 전처리 좌표를 새프레임 좌표로 바꾸어 게시하지 않는다.
5. RAW 실패/정렬/보정/초기 회복 확인에서는 동기 전처리를 기다린다. 움직임과 광학/target pixel 변경 시 reset, 연속 continuity 거절 시 sync 복귀도 유지한다.

## 비교 방법

기존 current 개발30장으로 MF2/mf4p/mf4o를 비교한 뒤, 변경 없이 validation119장과 과거 구름102장에서 MF2/mf4p를 검증했다. RAW는 센서 포화값4095와 해당 화각의 구름 gate, 전처리 영상은 포화객체가 제거된 합성 결과이므로 saturation=None/cloud gate off를 사용한다. 이 입력별 mask 의미는 기존 동작을 보존한 것이며 검출 알고리즘/threshold/후보 순서는 같다.

프레임/방식/RAW·전처리 실행순서를 교대했다. 같은 카메라 기하·왜곡·품질 게이트를 사용했고 실제 선택 backend와 SEP 호출 사유를 기록했다. 아래 표는 검출+솔브의 분리 비교이며 이미 만들어진 전처리 캐시를 사용한다. 전처리 비용을0으로 가정한 서비스 처리시간이 아니다. 실제 병행 처리 비용은 뒤의 auto 재생에서 별도로 측정했다.

`mf2`=전체1/2, `mf4p`=전체1/4→ROI1/2, `mf4o`=전체1/4→ROI1/2→원본 해상도다. 여기서 원본 해상도는 해당 입력의 전체 해상도다. RMSE는 솔빙 적합 오차이며 알려진 정답을 이용한 절대 pointing 정확도가 아니다.

## 개발30장

| 방식 | 영상 | 솔빙 성공 | SEP 호출 | 검출 중앙값 | 검출+솔브 중앙값 / p95 | RMSE 중앙값 |
|---|---|---:|---:|---:|---:|---:|
| mf2 | raw | 30/30 | 0 | 61.1ms | 106.1 / 313.4ms | 42.59″ |
| mf2 | preprocessed | 30/30 | 0 | 54.7ms | 59.8 / 75.6ms | 25.57″ |
| mf4p | raw | 30/30 | 0 | 24.6ms | 59.6 / 550.5ms | 42.21″ |
| mf4p | preprocessed | 30/30 | 0 | 24.1ms | 29.3 / 39.1ms | 25.97″ |
| mf4o | raw | 1/30 | 0 | 29.6ms | 276.4 / 1072.5ms | 16.03″ |
| mf4o | preprocessed | 30/30 | 0 | 31.4ms | 36.8 / 48.9ms | 24.77″ |

mf4o는 RAW1/30만 성공해 제외했다. 후보 중앙값8개로5개를 넘었기 때문에 정책상 SEP는 호출되지 않았다. 전처리에서만 잘 되는 방식을 RAW에도 그대로 적용하면 안 된다는 결과다. mf4p는 RAW/전처리 모두 성공했지만 개발RAW의 p95 지연이 MF2보다 높아 후속 자료로 확인했다.

## 독립 검증119장

| 방식 | 영상 | 솔빙 성공 | SEP 호출 | 검출 중앙값 | 검출+솔브 중앙값 / p95 | RMSE 중앙값 |
|---|---|---:|---:|---:|---:|---:|
| mf2 | raw | 117/119 | 0 | 60.9ms | 115.4 / 1100.0ms | 43.15″ |
| mf2 | preprocessed | 119/119 | 0 | 53.4ms | 68.8 / 117.9ms | 27.67″ |
| mf4p | raw | 119/119 | 0 | 23.6ms | 68.2 / 826.8ms | 41.49″ |
| mf4p | preprocessed | 119/119 | 0 | 24.4ms | 36.5 / 70.8ms | 27.67″ |

MF2의 RAW 실패2장은 전처리로 복구 가능했고 mf4p는 두 입력 모두119/119였다. mf4p가 검출 및 검출+솔브 중앙값/p95 모두 유리했다. 이 성공 수는 동일 자료1회 실행이며1초 Tetra3 제한과 시스템 부하의 영향을 받는다.

## 이전 구름 평가102장

| 방식 | 영상 | 솔빙 성공 | SEP 호출 | 검출 중앙값 | 검출+솔브 중앙값 / p95 | RMSE 중앙값 |
|---|---|---:|---:|---:|---:|---:|
| mf2 | raw | 0/102 | 0 | 111.0ms | 1308.3 / 2042.8ms | — |
| mf2 | preprocessed | 102/102 | 0 | 53.0ms | 60.3 / 76.8ms | 59.38″ |
| mf4p | raw | 0/102 | 0 | 79.6ms | 1206.2 / 1673.6ms | — |
| mf4p | preprocessed | 102/102 | 0 | 18.7ms | 25.3 / 36.4ms | 58.98″ |

두 방식 모두 RAW에서0/102, 전처리에서102/102였다. RAW 후보 중앙값은MF2 15개/mf4p 14개였으나 솔빙 가능한 패턴이 아니었다. 이는 '별 후보가 존재함'과 '신뢰할 수 있는 솔빙 성공'의 차이다. 현재 정책대로 SEP는 호출하지 않고 동기 전처리 복구가 필요하다. 이번 자료가 사용자 요청의 동기 예외를 유지해야 하는 근거다.

모든 실영상 비교에서 SEP 호출은0회였다. 부족후보/라이브러리 오류 시 SEP 전환과 충분후보에서 SEP 미호출은 별도 단위 검사로 확인했다. 신규 실영상에서 SEP의 구출 성공률을 측정한 결과로 해석하지 않는다.

## 기존 auto 스케줄 병행 재생

`benchmark_auto_detector.py`에서 실제 SolverSchedulingPolicy, LatestFrameWorker, worker3 전처리, MF 검출, Tetra3 cascade, PreprocessBiasTracker, SolveContinuityGate를 사용했다. validation 첫24장을0.4초 최소 간격으로 순차 제공했고 처리 시간이 넘으면 그만큼 늦어졌다. 원래 촬영 간격/카메라 최신프레임 drop을 그대로 재현한 실시간 카메라 테스트는 아니다. RAW는 전경, 전처리+검출은 배경, 완료 후보 솔빙은 전경에서 실행해 기존 역할 구분을 유지했다.

| 항목 | MF2 | mf4p |
|---|---:|---:|
| RAW 성공 | 23/24 | 24/24 |
| continuity 통과 | 20 | 22 |
| 동기 / 비동기 프레임 | 5 / 19 | 2 / 22 |
| 같은 프레임 bias 갱신 | 8 | 6 |
| 비동기 전경 중앙값 / p95 | 247.2 / 1305.6ms | 76.3 / 1039.1ms |
| 배경 전처리+검출 중앙값 / p95 | 1261.6 / 1658.4ms | 1078.2 / 1642.9ms |
| SEP 호출 | 0 | 0 |

mf4p는 준비2프레임 뒤22프레임을 async로 유지했고, background 처리 동안 현재RAW를 계속 처리했다. 비동기 전경 중앙값76.3ms는 배경 약1.08초와 더하지 않는다. 그러나 p95는약1.04초로 RAW 솔빙/완료 결과 검증의 지연이 남는다. 강제동기 예외가 사라지거나 GOTO가 항상76ms 안에 완료된다는 뜻이 아니다. 두 방식은 각각1회/24장 실행했으므로 수치의 일반화에 한계가 있다.

worker는 오래된 대기 작업을 교체했다(MF2 10개, mf4p 14개). 종료 직전 통계이므로 실행 중/대기 중 작업도 표시되며 종료 뒤 결과를 추가 적용하지 않았다. 이 harness는 정책을 구성요소 수준에서 재생한 것으로 전체 `solver()` 프로세스/IPC/SQM/UI/실제 마운트 정착시간을 측정하지 않는다. 정렬/보정/RAW 실패 예외 자체는 기존 경계 검사로 추가 확인했다.

## 기본값과 재현

현재 테스트 기본값:

```text
PIFINDER_DETECTOR=mf
MF_DETECT_BINNING=4
MF_DETECT_PYRAMID=2
MF_DETECT_RANKING=response
MF_DETECT_REFINE=0
MF_DETECT_SEP_FALLBACK=1
solver_preprocess_mode=auto
solver_preprocess_scale_workers=3
```

`MF_DETECT_SEP_FALLBACK=0`은 순수 native 비교용이다. 과거 MF2를 재현하려면 BINNING=2와PYRAMID=0을 함께 설정한다. `compare_cached_detectors.py`는 과거 순수 검출기 비교를 보존하기 위해 fallback을 끈다. 새 정책은 `compare_raw_preprocessed_detectors.py`로 비교한다. 기본 RAW 재생 도구도 worker3개를 사용하며 `--preprocess-workers`로2~4개 중 지정할 수 있다.

```bash
cd /home/pifinder/PiFinder_test/python
PYTHONPATH=. python3 scripts/compare_raw_preprocessed_detectors.py \
  /home/pifinder/PiFinder_test_data/corpora/20260915_fixed_validation \
  /home/pifinder/PiFinder_test_data/cache/validation \
  /home/pifinder/PiFinder_test_data/results/mf_primary_repeat.json \
  --modes mf2,mf4p

PYTHONPATH=. python3 scripts/benchmark_auto_detector.py \
  /home/pifinder/PiFinder_test_data/corpora/20260915_fixed_validation \
  /home/pifinder/PiFinder_test_data/cache/validation \
  /home/pifinder/PiFinder_test_data/results/mf_auto_repeat.json --mode mf4p
```

새 RAW 촬영/카메라 설정 변경/서비스 전환은 수행하지 않았다. 원본과 프레임별 좌표는 로컬에 보관하고 저장소에는 집계만 포함한다. 두 운영 저장소 main은 수정 없이 유지했고 pifinder.service는 기존 `/home/pifinder/PiFinder/python`에서 active였다. 부팅 경로와 영구 unit은 변경하지 않았다.

## 최종 검사

검출/fallback·스케줄·프레임짝·worker·bias 관련61개 검사, 내부 병렬성 추가 후 관련53개 검사 통과. 최종 전체 unit/smoke는 **2293 passed, 2 skipped, 716 deselected**, 기존 경고8개였다. mypy는201파일 통과, Ruff 검사/포맷373파일 통과. 마지막 오프라인 재생 기본 worker도3개로 맞춘 후 실제2프레임 smoke 재생과 lint/format을 확인했다. 하드웨어 integration 전체 검사 또는 실제 서비스/GOTO 테스트를 수행했다는 뜻은 아니다.
