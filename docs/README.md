# mf_detect_star 문서

이 폴더는 detector의 구현 결정, 장기 구조, 후속 연구를 저장소와 함께 버전 관리한다.

최신 구현은 C ABI v1과 PiFinder adapter, MF4p, 병렬 전처리 비교를 포함한다.
[현재 실측 기본값](test_cedar_free_20260915/FIELD_GUIDE_ko.md)과
[라이선스 적용 범위](../LICENSING.md)를 먼저 확인한다.

[라이선스·정본 통합 완료 기록](CONSOLIDATION_RESULTS_ko.md)에서 관리 위치와
새 checkout 검증 결과를 확인할 수 있다.

[선택적 GPU 전처리](GPU_PREPROCESS_ko.md)는 Raspberry Pi V3D의 DoG 필터
실험 옵션이다. CPU 기본값과 [실측 결과](GPU_PREPROCESS_RESULTS_20260923_ko.md)를
함께 확인한다.

[다음 가속 개선 판단](NEXT_ACCELERATION_DECISION_20260923_ko.md)은 GPU 병목 분리,
공유 메모리 타일과 CPU NEON 누적의 시험 결과를 정리한다.

[Pi 4·5 CPU 누적 최적화](CPU_PREPROCESS_ko.md)는 적용된 NEON 경로와
자동 선택·NumPy 복귀 옵션, 빌드와 검증 방법을 설명한다.

## 읽는 순서

1. [고속 하늘 전처리 및 별 후보 보존 설계](mf_fast_sky_preprocessing_design_ko.md)
   현재 구현의 우선 결정 문서다. 광해·얇은 구름·포화 광원 처리, PSF filter, C++ 전환
   순서를 정의한다.
2. [전용 천체 detector 개발 방향 및 설계](mf_native_detector_design_ko.md)
   LensProfile, 중앙·주변 tile planner, C ABI, shared-memory, solver adapter를 포함한 장기
   구조를 정의한다.
3. [AI 기반 별 검출 조사 및 적용 설계](mf_ai_star_detection_research_ko.md)
   고전 전처리의 한계가 실제 corpus에서 확인된 이후에만 검토할 AI 보조 경로를 정리한다.

## 구현 상태와 문서의 관계

`v0.1.0`은 full-frame offline reference 구현이다. 현재 코드에는 mesh median/MAD 배경·잡음
추정, 포화/halo mask, zero-sum PSF response, centroid/shape gate와 합성 회귀 테스트가 있다.

아직 구현하지 않은 항목은 다음과 같다.

- 중앙 우선·주변 radial tile scheduler
- 6 mm/16 mm LensProfile과 distortion calibration
- detector 코어의 row streaming과 ARM NEON (전처리 시간 누적 NEON은 구현됨)
- 선택적 SEP C 또는 AI backend

설계 문서가 현재 코드보다 앞선 내용을 포함하므로, 완료되지 않은 항목을 구현 완료로 해석하지
않는다. 구현 상태는 저장소의 [README](../README.md), [CHANGELOG](../CHANGELOG.md), tag를
기준으로 판단한다.

## 외부 PiFinder 참조

문서에서 현 PiFinder 구현을 인용하는 링크는 별도 저장소
[`hjoungjoo/MF_PiFinder`](https://github.com/hjoungjoo/MF_PiFinder)를 가리킨다.
PiFinder는 `python/mf_detect_star`의 고정 커밋 submodule로 이 저장소를 참조한다.
통합 코드는 [integrations/pifinder](../integrations/pifinder/README.md)가 정본이다.

[현재 Cedar/MF4p 직접 비교](test_cedar_free_20260915/CEDAR_AB_RESULTS_ko.md)는
같은 영상·공통 품질 기준에서 측정한 검출/솔빙 속도와 RMSE를 정리한다.
