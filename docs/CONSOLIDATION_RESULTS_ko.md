# 라이선스 적용 및 단일 정본 관리 — 완료 기록

## 적용 결과

사용자 요청에 따라 native 검출기에 Cedar Detect와 동일한 **5년 후 MIT 전환**
라이선스 조건을 적용했다. `LICENSE`, 소스 SPDX 표기, README, 설계 문서,
CI 검사와 빌드 산출물의 `build/licenses/`에 반영했다.

Cedar 원문은 FSL-1.1-MIT를 명칭으로 사용하지만 전환 기간이 표준과 다르므로
`LicenseRef-Cedar-FSL-1.1-MIT-5year`로 구분했다. Cedar의 고정 커밋 원문과
Functional Source License 이후 본문이 동일함을 SHA256으로 검사한다.
MF 저작권 고지는 기존 PiFinder contributors를 유지했다.
[LICENSING.md](../LICENSING.md)에 범위·출처·이전 MIT 고지를 정리했다.

PiFinder에서 가져온 소스의 GPL과 이전 MIT 배포 권한은 보존한다.
이번 작업은 이를 Cedar 조건으로 일괄 재라이선스한 것이 아니다.

## 관리 위치

| 구성 | 정본 위치 |
|---|---|
| C++ 검출기, C ABI, native 테스트 | `src/`, `include/`, `tests/` |
| 전처리·검출 연결·프로필·anchor·SEP/cloud gate | `integrations/pifinder/PiFinder/` |
| 수집·검출기 비교·병렬 처리 측정 도구 | `integrations/pifinder/scripts/` |
| 관련 Python 테스트 | `integrations/pifinder/tests/` |
| 설계 문서·실험 계획/결과/집계 | `docs/` |
| 기존 출처·이동 전 파일 해시 | `integrations/pifinder/SOURCE.json` |

총 23개 Python 소스/도구/테스트를 통합했다. PiFinder에 있던 실험 문서/집계
46개를 정본에 합쳤다. 서로 달랐던 STAGE1 기록은 이전 native 사본을 history에
남겨 보존했다. PiFinder의 독립 복사본은 고정 Git submodule 참조와 상대 symlink로
대체했다. PiFinder가 사용하는 정확한 버전은 부모 저장소의 gitlink가 결정한다.

기본 .so도 정본 source tree의 `build/libmf_detect_star.so`에서 읽는다.
형제 `/home/pifinder/mf_detect_star_test/build`를 암묵적으로 사용하지 않는다.
명시적인 `MF_DETECT_LIBRARY` override는 유지했다.
PiFinder의 최초 checkout 및 CI는 `scripts/setup_mf_detect_star.sh`로 초기화/빌드한다.
새 checkout을 검사하면서 submodule URL이 로컬 경로가 아닌 기존 GitHub 원격임도
확인했다. 실행 중 원격 branch 최신 버전을 자동으로 따라가지 않는다.

## 검증

- native 빌드 및 합성 회귀: **6/6 통과**.
- 원래 테스트 checkout에서 전체 Python unit: **2310 passed, 2 skipped,
  723 deselected**, 기존 경고 8개.
- 추가 원격 URL/경로 검사: **3 passed**.
- mypy: **204 source files** 통과.
- Ruff: PiFinder **382파일** 및 canonical 통합 코드/검사 도구 통과.
- 같은 합성 입력의 이전/이후 **6개 별 좌표·flux·backend 완전 일치**.
- 실측 validation 첫 3장의 기존 비교 도구 실행 성공: 전처리 warmup 제외,
  MF4p 및 SEP의 RAW/전처리 각각 **2/2 솔빙 성공**. 성능 순위 재평가는 아니다.
- 별도 새 checkout에서 GitHub submodule 초기화, native 빌드/6개 회귀,
  Python 통합 검사 **24개 통과**. 새 checkout 자체의 .so 사용과 이전 결과의
  좌표/flux 일치까지 확인했다.
- shell 구문, 공백, 라이선스 본문/적용 범위/파일 목록 검사 통과.

검사 로그는 `/home/pifinder/PiFinder_test_data/results/`의
`tests_consolidation.log`, `mypy_consolidation.log`, `consolidation_smoke/`,
`fresh_consolidation_build.log`, `fresh_consolidation_tests.log`에 보관했다.
처음 `/tmp`에서 시도한 새 checkout은 256MiB tmpfs 용량이 부족해 정리했고,
테스트 데이터 디스크에서 새로 checkout하여 위 검증을 완료했다.

## 운영 상태

운영 PiFinder 및 mf_detect_star의 main 소스, 서비스와 부팅 경로는 변경하지 않았다.
MF4p + auto, SEP 보조 조건, RAW 실패·정렬·보정 때 대기하는 정책도 그대로다.
원본 관측 데이터와 장비 설정은 이동하거나 원격에 올리지 않았다.
코드·문서 변경은 기존 두 저장소의 승인된 테스트 브랜치로 푸시한다.
