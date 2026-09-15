# 라이선스 적용과 관리 위치 통합 — 작업 전 계획

사용자 요청에 따라 Cedar Detect의 라이선스 조건을 native 검출기에 적용한다.
참조는 cedar-detect `2f403b8435259263f2a4fcd43f526918fe546d77` LICENSE.md이다.
원문은 FSL-1.1-MIT 표기를 사용하지만 MIT 전환 시점은 공개 5년 후이다.
표준 2년 FSL과 구분하는 LicenseRef를 사용하고 실제 본문은 동일하게 유지한다.
MF 저작권 고지는 기존 PiFinder contributors를 보존하며 Cedar 저작권자를
MF의 저작권자로 기재하지 않는다. 기존 MIT 배포 이력도 보존한다.

검출기 native 소스/헤더/시험과 통합 Python 모듈/비교 스크립트/관련 테스트,
실험 문서의 정본은 이 저장소로 모은다. PiFinder에서 옮기는 GPL 코드는
integrations/pifinder 아래에서 기존 GPL 라이선스와 출처를 유지한다.
PiFinder 테스트 저장소는 고정 커밋 submodule과 호환 경로 심볼릭 링크로
정본을 사용하며 기본 .so 경로도 이 submodule build로 통일한다.
PiFinder 서비스·카메라·부팅 경로·실험 알고리즘 정책은 변경하지 않는다.

구성 변경 전후 합성 검출 출력, native 회귀, Python 전체 unit/type/lint,
실측 캐시 smoke, 새 checkout의 초기화/빌드 및 문서 링크를 검증한다.
원본 영상과 장비 설정은 기존 로컬 저장 위치를 유지한다.
승인된 두 저장소 테스트 브랜치에 계획과 완성 결과를 나누어 푸시한다.
