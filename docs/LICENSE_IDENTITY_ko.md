# MFDS 라이선스 표기 정리 — 2026-09-16

> 이 문서는 2026-09-16 변경 기록입니다. 2026-09-23 제품 정체성과
> MagicFly 자체 기여 범위의 표기 정리는 [MFNavis 판매 기준](MFNAVIS_COMMERCIAL_ko.md)을 따릅니다.

## 작업 범위

MFDS가 다른 프로젝트의 라이선스 허락이나 권리자에 종속되는 것처럼 보이던 설명을 MFDS 자체 정책으로 정리한다. 현재 라이선스 식별자는 `LicenseRef-MFDS-FSL-1.1-MIT-5year`로 통일한다.

- LICENSE 서문, README 영문·한글, LICENSING, 상용 사용 안내와 MFDS 라이선스를 설명하는 설계·통합 기록을 정리한다.
- native 소스 SPDX 고지, LICENSES의 식별자 파일, 검사 도구를 같은 이름으로 변경한다.
- 기존 Functional Source License 본문, 5년 후 MIT 전환 조건, 저작권 고지, GPL 통합 코드와 과거 MIT 권한은 유지한다. 공개일과 기산일도 바꾸지 않는다.
- 과거 외부 검출기 성능 비교와 제3자 소스 출처 기록은 MFDS의 현재 라이선스 설명과 구분한다. 최초 이관 해시 목록인 PUBLICATION.json과 SOURCE.json은 원본 기록으로 보존한다.

## 검증

Functional Source License 제목 이후 본문의 SHA256이 기존 `8f822494dbb1e4ef5f655245257cc449b81450e59dd122f6f9197e1d7622b8c9`와 동일한지 검사한다. 현재 LICENSE·LICENSING·상용 사용 안내에는 외부 검출기 이름이 남지 않도록 검사하며 모든 native SPDX와 식별자 파일 연결도 확인한다.

## 적용 버전

MFDS v0.2.1과 이를 고정하는 PiFinder m2.6.6으로 정식 패치 릴리즈한다. 과거 태그를 이동하지 않는다.
