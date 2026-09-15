# Cedar Detect와 현재 MF4p 직접 비교

## 결론

이번 동일 자료/공통 품질 기준 비교에서는 **Cedar가 별 검출 자체는 빠르고,
MF4p가 광해 RAW 솔빙 성공률과 전처리 영상 RMSE에서 유리**했다.
구름 RAW에서는 양쪽 모두 실패했지만 Cedar는 후보 부족을 빨리 판단하고,
MF는 남은 후보로 솔빙을 시도해 약 1.17초를 소비했다. 모든 지표에서 MF가
우세한 결과가 아니며 현재 알고리즘·기본값은 변경하지 않았다.

## 조건

- 기존 `20260915_fixed_validation` 처음24장: warmup 제외 23장.
- 기존 `20260903_cloud_coordinate_jitter`의 17~40번째24장: 모두 전처리 준비됨.
- 동일 RAW·전처리 캐시, 원본 SHA256 검증. 같은 기하·왜곡·warm/포화 필터,
  구름 자료의 RAW cloud gate, 최대48개, Tetra3 중심→전체 cascade를 사용했다.
- 양쪽 최소7개 매칭, RMSE<=180 arcsec, false probability<=5e-5의 공통 기준.
  운영 Cedar 경로는 최소6개를 허용하는 분기도 있으므로 이것은 전체 운영
  cascade의 비교가 아니라 **동일 품질 기준의 검출기 비교**다.
- Cedar는 운영 설정의 `(RAW >> 4)` 8-bit, sigma8, max_size10,
  binned candidate, hot-pixel 검출. MF는 기존 MF4p 기본값/원본16-bit 버퍼.
  threshold 의미가 달라 같은 수치로 강제하지 않았다.
- 실행 중 `cedar_detect.service`(PID708, port50551)에 inline gRPC 요청.
  공유 메모리는 사용/수정하지 않았고 서버 시작/종료/설정 변경 없음.
- 검출 순서와 RAW/전처리 순서를 프레임마다 교대했다. 보조 SEP 호출은 0회.
- 검출 시간은 입력 변환+호출/전송+공통 필터 포함. Cedar의 inline RPC와 MF의
  ctypes 호출 방식이 다르므로 순수 C++ 코어 성능 비율로 해석하면 안 된다.
  전처리는 캐시를 사용해 **전처리 생성 비용은 아래 시간에 포함되지 않는다**.

## 측정 결과

단위는 ms, 시간과 RMSE는 중앙값이다. p95는 검출+솔빙 시간의 95백분위다.

| 자료/입력 | 검출기 | 솔빙 성공 | 검출 | 검출+솔빙 | p95 | RMSE(arcsec) | 매칭 별 |
|---|---|---:|---:|---:|---:|---:|---:|
| 고정·광해 RAW | Cedar | 5/23 | 18.6 | 1096.6 | 1580.0 | 44.94 | 9 |
| 동일 RAW | MF4p | 23/23 | 24.8 | 73.6 | 999.7 | 41.51 | 21 |
| 고정·광해 전처리 | Cedar | 23/23 | 21.8 | 36.3 | 72.5 | 40.20 | 31 |
| 동일 전처리 | MF4p | 23/23 | 26.1 | 40.7 | 52.5 | 26.17 | 30 |
| 구름 RAW | Cedar | 0/24 | 66.0 | 66.0 | 82.6 | — | — |
| 동일 RAW | MF4p | 0/24 | 81.9 | 1167.2 | 1582.5 | — | — |
| 구름 전처리 | Cedar | 24/24 | 20.8 | 31.5 | 45.6 | 87.35 | 13 |
| 동일 전처리 | MF4p | 24/24 | 20.9 | 28.0 | 57.1 | 81.66 | 12 |

시간 집계에는 성공·실패 모두 포함하며 RMSE/매칭 수는 성공분만 포함한다.
RAW에서 실패한 시간은 좌표를 얻는 데 성공한 시간이 아니다. 구름 RAW Cedar의
후보 중앙값은1개라 Tetra3 시도를 못 했고 MF는12개여서 실패할 솔빙에 시간을 썼다.
기존 정책상 MF 후보가5개 이상이면 SEP로 전환하지 않는다.

Cedar가 보고한 순수 `algorithm_time` 중앙값은 고정 RAW9.21ms/전처리9.52ms,
구름 RAW10.36ms/전처리9.47ms였다. MF는 이 비교에서 동등 범위의 코어 단독 시간을
추출하지 않았으므로 코어끼리 몇 배라는 결론은 내리지 않는다.

## 품질 해석

- 고정 전처리의 RMSE 중앙값은 MF가 약34.9% 낮았고 23장 모두 MF의 RMSE가 낮았다.
- 구름 전처리의 RMSE 중앙값은 MF가 약6.5% 낮았고 24장 중17장에서 MF가 낮았다.
  p95 RMSE는 Cedar125.18″, MF101.12″였다.
- RAW는 성공 표본이 달라 전체 성공분의 중앙값끼리 정확도를 단정하지 않는다.
  둘 다 성공한5장만 보면 Cedar44.94″, MF46.80″로 Cedar가 조금 낮았고,
  MF의 RMSE가 낮은 것은2/5장이었다. MF의 주된 RAW 이득은 **성공률**이다.
- 전처리 좌표의 두 검출기 간 각거리 중앙값은 고정39.09″/구름66.23″였다.
  구름 최대 차이는169.88″였다. 기준 천체의 정답 지향 좌표가 없는 자료이므로
  낮은 RMSE를 절대 관측 방향 정확도가 높다는 증명으로 보지 않는다.
- 광학계가 다른 두 세션의 RMSE를 직접 비교하지 않는다. 프레임 수가 적고
  고정 상태 자료이므로 일반적인 성공률이나 움직이는 망원경 성능을 보장하지 않는다.

속도상 추가 개선 후보는 MF의 **구름 RAW 실패 판단 지연**이다. 이것을 줄이려면
유효한 희미한 별을 버리지 않는 조건을 별도 검증해야 한다. 이번에는 변경하지 않았다.

## 재현과 보관

2026-09-15 영구 제거: Cedar 서버·프로토콜·전용 비교 도구를 삭제했다.
아래 명령은 당시 실험의 기록이며 현재 체크아웃에서는 실행할 수 없다.
기존 측정 데이터와 출처·라이선스 기록은 보존한다.

PiFinder 테스트 checkout에서 다음 명령을 실행한다. 기존 Cedar 서버와 별도
설치된 protobuf 파일이 필요하다. 이 도구는 기본 서비스 경로에서 호출되지 않는다.

```bash
PYTHONPATH=python python3 \
  python/mf_detect_star/integrations/pifinder/scripts/compare_cedar_reference.py \
  /home/pifinder/PiFinder_test_data/corpora/20260915_fixed_validation \
  /home/pifinder/PiFinder_test_data/cache/validation \
  /home/pifinder/PiFinder_test_data/results/cedar_mf_repeat.json \
  --frames 24 \
  --cedar-proto-dir /home/pifinder/PiFinder/python/PiFinder/tetra3/tetra3
```

구름 자료는 corpus/cache를 바꾸고 `--start 16 --frames 24 --wide`를 추가한다.
Cedar 구현·protobuf·binary를 mf_detect_star에 포함하지 않는다. 명시된 외부
프로토콜 경로에서만 비교 도구가 읽는다. 실행파일/소스 해시는 집계 JSON에 기록했다.
서버가 버전 문자열을 반환하지 않아 별도 버전 번호는 추정하지 않았다.

상세 좌표/프레임별 시간은 로컬 `PiFinder_test_data/results/cedar_mf_validation.json`,
`cedar_mf_cloud.json`에 보관하고 좌표 없는 집계만
[cedar_mf_direct.summary.json](cedar_mf_direct.summary.json)에 저장했다.
실제 실행 188개 arm 결과의 프레임 짝/개수, 후보 상한, 시간/품질 범위 및
Ruff/구문 검사를 확인했다. 검출 알고리즘과 운영 pifinder.service(PID715)는 유지했다.
