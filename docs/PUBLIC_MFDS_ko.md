# MFDS 공개 이관 — 2026-09-16

사용자 요청으로 최종 MF Detect Star 소스와 자료를 `hjoungjoo/MFDS`에서 공개한다.
기준은 이전 `mf_detect_star`의 `2f556b448aa21782c478cd47215ab54899055cf7`이며,
149개 추적 파일의 원래 blob·SHA256·모드와 출처는 `PUBLICATION.json`에 보존했다.
새 저장소는 최종 스냅샷에서 시작하므로 비공개 Git 과거 이력은 공개하지 않는다.
원본 관측 영상·장비 설정·좌표 기록·개인 키·빌드/가상환경 캐시는 포함하지 않는다.

MFDS README와 상용 사용 안내·이관 출처 문서를 정리했다. native 검출·전처리
코드, ABI, 프로세스 통신과 성능 기본값은 바꾸지 않았다. 내부 프로그램 및
PiFinder submodule 경로의 `mf_detect_star` 이름은 호환성을 위해 유지한다.

기존 LICENSE 전문과 GPL·MIT 고지 및 권리 범위를 유지한다. 저장소를 새로
공개했다고 이전 버전의 5년 기한이 다시 시작되거나 MIT 권한이 사라지지 않는다.
GPL 코드에 MF native의 상용 제한을 추가하지 않는다. 적용 범위는 LICENSING.md,
현재 상용 허락은 COMMERCIAL_USE.md와 LICENSE를 함께 읽는다.

PiFinder는 m2.6.4에서 공개 MFDS의 커밋을 고정해 사용한다. CI에서 개인 키를
요구하지 않으며, 기존 저장소 삭제는 MFDS clone·build·CI와 전환 검증 후 진행한다.
Cedar를 복원하거나 예전 비공개 코드 이력을 새 공개 저장소로 가져오지 않는다.
