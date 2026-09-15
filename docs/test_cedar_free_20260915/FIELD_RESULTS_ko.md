# 기본값 확정·실측 비교·좌표 저장 변경 결과

후속 관리 통합: 현재 정본은 mf_detect_star 저장소이며 PiFinder는 submodule로
참조한다. 아래는 통합 이전 시험 시점의 기록이다.

## 결정

**MF4p + auto**를 테스트 기본값으로 확정했다. 전처리 scale worker는 3개,
RAW 실패/정렬/보정의 같은 프레임 대기를 유지한다. 선택 근거는 기존 119장
검증·구름 102장 결과와 이번 동일 영상 재실행이다. 항상 병렬 anchor는
고정 상태에서 유망하지만 빠른 흔들림/실제 마운트 연계가 검증되지 않아 별도
비교기로 남겼다. 서비스·부팅 경로는 변경하지 않았다.

공통 프로필, 실측 일괄 비교 명령, 향후 저장 좌표의 해석은
[FIELD_GUIDE_ko.md](FIELD_GUIDE_ko.md)에 정리했다.

## 이번 재실행

기존 `20260915_fixed_validation`의 처음 24장으로 전체 비교를 실행했다.
전처리 warmup 1장을 제외해 paired 비교는 23장이다. 노출/광학계는 캐시에
기록된 동일 자료를 사용했고 캐시와 RAW SHA256을 검사했다.

| 검출기 | RAW 솔빙 | 전처리 솔빙 | RAW 검출 중앙값 | 전처리 검출 중앙값 |
|---|---:|---:|---:|---:|
| MF4p 기본 | 23/23 | 23/23 | 24.3ms | 23.9ms |
| MF2 | 23/23 | 23/23 | 58.4ms | 52.3ms |
| SEP | 22/23 | 23/23 | 53.2ms | 45.2ms |
| MF4p, 보조 꺼짐 | 23/23 | 23/23 | 24.1ms | 23.9ms |
| MF4o 원본 정밀화 | 14/23 | 23/23 | 78.2ms | 31.9ms |
| MF8p | 5/23 | 23/23 | 8.7ms | 9.6ms |

MF4o RAW의 14건은 SEP 보조 호출이 발생했다. MF4p/MF2의 보조 호출은 0건이다.
SEP 비교군의 각 arm에는 순수 SEP 23회가 포함된다. `sep_calls`와
`sep_fallback_calls`를 분리해 순수 SEP 호출을 0회로 오해하지 않게 했다.
빠르지만 RAW 성공률이 낮은 MF8p를 기본값으로 선택하지 않았다.

실제 전처리와 솔빙을 실행한 24프레임 timing harness:

| 실행 | RAW 솔빙 | 발행/사용 | foreground 중앙값 | foreground p95 |
|---|---:|---|---:|---:|
| MF4p auto, async 구간 | 24/24 | 전체 발행 22, sync 2 / async 22 | 94.7ms | 1067.1ms |
| MF2 auto, async 구간 | 23/24 | 전체 발행 20, sync 5 / async 19 | 206.2ms | 948.5ms |
| 독립 anchor worker | 24/24 | RAW 12 → anchor+RAW 변화량 12 | 92.1ms | 1023.4ms |

anchor worker는 전처리/검출/솔빙이 메인과 다른 thread/solver instance임을
검사했고, foreground에서 전처리 완료를 기다리지 않았다. 기준점 4회가 수락됐다.
이 측정은 마운트/UI/SQM/카메라 IPC를 제외한다. 약 1초 p95가 남아 있으므로
GOTO 지연 문제가 해결됐다고 선언하지 않는다. 짧은 샘플의 p95만으로 순위를
정하지 않았고, 기존 대규모 자료의 성공률/정확도/속도를 함께 고려했다.

추가로 **새 캐시 생성부터** MF4p/SEP 3프레임 전체 절차를 실행해 완료했다.
짧은 자료의 anchor 안정성은 수치 대신 표본 부족으로 보고한다.

## 관측 좌표 저장

테스트 소스의 TIFF, field capture, 텔레메트리, 단일 촬영/텔레메트리 PNG
동반 JSON, 노출 sweep, stage dump에 목표와 관측 방향 스냅샷을 추가했다.
같은 목표 ID의 좌표 변경도 기록한다. 상세 형식은 가이드를 따른다.
이 수정은 **테스트 서비스로 전환한 후** 해당 앱 저장 경로에 적용된다.
외부 corpus 수집기는 지금도 실행할 수 있으며 구버전 API의 누락을 표시한다.

현재 서비스의 RAW 출력은 꺼져 있었다(`processing_enabled=false`, HTTP 204).
solution도 HTTP 503이었다. 읽기 전용 현장 수집 확인은 0장으로 끝났고,
이미지나 목표 좌표를 확보했다고 계산하지 않았다. 기록기에 명확한 오류를
추가했다. 카메라 설정/서비스를 변경해서 수집을 강제하지 않았다.

기록 검증에서는 실제 TIFF 인코딩/디코딩 후 픽셀 보존과 좌표 내장, 같은 픽셀의
중복 판정, RAW/캐시 불일치 거부, 목표와 노출 시각 구분, 솔빙 실패 중 목표 유지,
동일 ID 좌표 변경, 목표 삭제, RA 0도 경계 각거리, NaN 처리, 짧은 실패 자료를
확인했다. 실제 저장 목표가 없으면 null로 남기고 솔빙 좌표로 만들어 채우지 않는다.

## 검사와 보관

- 전체 unit 검사: **2307 passed, 2 skipped, 723 deselected**, 기존 경고 8개.
- 이후 추가된 수집기 확인을 포함한 관련 검사: **88 passed**.
- 전체 mypy: **204 source files** 통과.
- Ruff lint/format: **381 files** 통과. shell 구문·diff 공백 검사 통과.
- 운영 pifinder.service: active, PID 715, WorkingDirectory는 운영
  `/home/pifinder/PiFinder/python`. 테스트 서비스 전환/재시작 없음.

로컬 결과: `/home/pifinder/PiFinder_test_data/results/field_suite_validation/`,
`field_suite_fresh_cache/`, `tests_field.log`, `mypy_field.log`.
공유용은 `field_suite_summary.json`과 문서만 복사했다. 원본·개별 좌표·장비 설정은
로컬에 유지했다. 두 기존 저장소의 승인된 `test/cedar-free-20260915` 브랜치로
작업 전 계획과 최종 코드/문서를 나누어 푸시한다.
