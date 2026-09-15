# Cedar 실행 의존성 제거 — 2026-09-15

사용자 요청에 따라 Cedar Detect를 재사용하지 않는다. 별도 설치 Cedar 서버를
호출하던 `compare_cedar_reference.py`를 삭제하고 RAW/전처리 비교 도구의
미사용 `--cedar-address` 옵션을 제거했다. MF RAW/전처리 및 검출 방식 간
비교 도구는 유지한다. 이전 Cedar 실측 결과는 역사적 자료로 보존한다.

검출·전처리 네이티브 구현, 기본값, memfd 프로세스 통신은 변경하지 않았다.
MF의 기존 라이선스 조건과 SPDX 식별자 및 출처 고지는 그대로 유지한다.
이 작업은 라이선스 변경이나 과거 Git 이력 삭제가 아니다.

검증: `tools/check_layout.py`, MF 네이티브 테스트 및 변경 Python의 Ruff 검사를
수행한다. 장비의 Cedar 서비스/배포 캐시 삭제와 운영 검증은 PiFinder의
`docs/CEDAR_REMOVAL_ko.md`에 기록한다. 원격 푸시는 사용자 요청으로 보류한다.
