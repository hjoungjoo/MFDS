# 1단계 — 직접 호출과 정확도 비교 준비

작업 전 계획을 별도 테스트 브랜치에 먼저 푸시했다. 현재 변경은 MIT 독립 코어를 Python에서 직접 호출하는 C ABI 1과 선택적 원본 좌표 재측정이다. mfds_detect_u16은 기존 동작, mfds_detect_u16_refined는 비닝 검출 뒤 원본 7x7 원형 aperture와 독립 annulus 배경을 사용하는 실험 경로다. 기본 코어 옵션은 변경하지 않았다.

C API는 호출자 버퍼만 사용하고 예외를 경계 밖으로 내보내지 않는다. 파일 IO/프로세스 생성/gRPC 없이 기존 PiFinder 전처리 출력과 같은 좌표 계약에 연결한다. Cedar/SEP 내부 구현을 복사하지 않았다.

첫 개발 표본: 구름 cache 11장에 SEP, MF 비닝2, MF 원해상도 모두 11/11 솔브. RMSE 중앙값은 각각 약99.09/99.29/99.69 arcsec. 작고 편향된 개발 표본이므로 우열 또는 전체 성능을 확정하지 않는다. 상세 비교는 MF_PiFinder 테스트 브랜치와 로컬 PiFinder_test_data/results에 기록한다. 원본 재측정의 이득은 아직 측정 중이며 default로 승격하지 않는다.

검증: 기존 독립 합성 테스트 5/5. Python adapter의 알려진 합성별 좌표/포화 hot pixel/flux 순서/ABI 오류 검사도 수행한다. 전체 영상과 속도 결과는 다음 문서에서 갱신한다.
