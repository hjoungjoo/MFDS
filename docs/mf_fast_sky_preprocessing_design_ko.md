# PiFinder 고속 하늘 전처리 및 별 후보 보존 설계

> 작성일: 2026-08-25
> 상태: 전용 detector 구현의 우선 설계 결정
> 범위: 광해, 구름, 달·가로등, flare, 비네팅, 센서 결함을 별 검출 전에 낮은 비용으로 억제하고 관측 가능한 점광원을 보존한다.
> 관련 문서: [전용 native detector 설계](mf_native_detector_design_ko.md), [AI 별 검출 조사](mf_ai_star_detection_research_ko.md)

## 1. 최종 권고

첫 제품 경로에는 AI denoiser나 full-frame 별 segmentation 모델을 넣지 않는다. 가장 효율적인
기본 경로는 다음 조합이다.

1. 작은 mesh마다 강건한 배경과 지역 잡음을 한 번 계산한다.
2. 포화 광원, halo, bad pixel, 사용할 수 없는 하늘을 mask한다.
3. 원본에서 배경을 뺀 값을 지역 잡음으로 정규화한다.
4. 렌즈의 별 PSF 크기에 맞는 separable matched filter 또는 DoG를 적용한다.
5. 국소 최대값만 원본 RAW의 작은 patch에서 centroid와 형상을 검증한다.
6. 중앙부터 시작하되 부족하면 품질이 좋은 주변 tile을 순차 처리한다.

이 과정은 “노이즈가 제거된 새 영상”을 만드는 작업이 아니다. 출력은 아래 네 가지이며 RAW는
읽기 전용으로 유지한다.

- `B(x,y)`: 저주파 배경 지도
- `sigma(x,y)`: 지역 잡음 지도
- `M(x,y)`: 포화·광원·센서 결함·무효 영역 mask
- `R_s(x,y)`: PSF scale별 점광원 응답

따라서 구름 뒤의 별을 AI가 만들어 내거나 달 주변을 그럴듯하게 복원할 위험이 없다. 보이는
별만 남기고, 보이지 않는 구역은 `NO_USABLE_SKY` 또는 낮은 tile 점수로 정직하게 제외한다.

이 설계의 출발점인 PiFinder의 [`sep_detect.py`](https://github.com/hjoungjoo/MF_PiFinder/blob/main/python/PiFinder/sep_detect.py)는 이미 2x2 binning, SEP mesh
background subtraction, local RMS, 3x3 matched filter를 사용하므로 알고리즘 방향은 맞다.
우선 개선할 것은 알고리즘 교체보다 Python 경로의 전체 프레임 `float32` 변환과
`bkg.back()`, `bkg.rms()`, `data_sub` 배열 생성, 단계별 재검출을 없애는 일이다.

## 2. 왜 AI가 우선순위가 아닌가

광해와 완만한 구름 glow는 별보다 공간 주파수가 낮다. 별은 렌즈별 PSF 크기의 작은 점이고,
포화된 달·가로등은 밝기와 연결 영역만으로 먼저 식별할 수 있다. 이 차이는 학습 없이 지역
통계와 작은 convolution으로 잘 분리된다.

AI의 이득이 예상되는 장면은 복잡한 flare ghost, 나뭇가지·건물 불빛, 매우 불규칙한 구름
경계처럼 물리 규칙만으로 애매한 경우다. 그러나 full-frame AI에는 다음 비용이 생긴다.

- 6 mm와 16 mm, 센서, 초점, 이슬, 노출·gain별 자료를 모아야 한다.
- no-star frame을 충분히 넣지 않으면 false star를 만들 수 있다.
- 정량화와 입력 축소가 희미한 1~3 pixel 별을 지울 수 있다.
- 모델 추론 전에도 background normalization과 mask가 필요하므로 고전 전처리가 없어지지 않는다.

실제로 공개된 직접 사례의 Raspberry Pi 4B + Coral 결과도 640x480 MobileUNet 한 장에 평균
265.5 ms였다. 연구 가능성을 보여 주지만 PiFinder의 기본 전처리로 삼을 근거는 아니다.

## 3. 환경 요인별 처리 원칙

| 환경 | 영상에서의 성질 | 기본 처리 | 한계와 안전 동작 |
| --- | --- | --- | --- |
| 도시 광해·하늘 gradient | 넓고 완만한 가산 배경 | mesh별 robust background 보간 후 감산 | 국부 광원이 mesh 대부분을 차지하면 해당 cell을 이웃으로 보간하거나 제외 |
| 얇은 구름·박무 | glow 증가와 별 감쇠가 함께 발생 | 배경 감산 + local RMS + tile 품질 점수 | 감쇠된 별을 복구하지 않음. 관측 가능한 SNR의 별만 통과 |
| 두꺼운 구름 | 별 정보 자체가 없음 | 높은 RMS/낮은 점광원 수로 tile 제외 | AI 복원 금지, `NO_USABLE_SKY` |
| 달·가로등·포화 광원 | 포화 core, bloom, 넓은 halo | 포화 component mask와 크기 비례 dilation; 잔여 halo는 배경 model | halo·ghost가 별 크기 구조를 만들면 tile 제외 또는 후보 형상 gate |
| flare·ghost | 넓은 arc, 원형 반사, 국소 contrast | gradient/structure 점수, 비점광원 형상 거절 | 고전 규칙의 실패가 실증된 뒤에만 작은 tile 분류기 검토 |
| 비네팅 | 반경 방향 저주파 변화, 가장자리 SNR 하락 | lens validity/flat map + 지역 배경·잡음 | 6 mm 가장자리를 일괄 crop하지 않고 radial profile 사용 |
| hot/warm pixel | 센서 좌표에 고정된 1 pixel spike | dark/cap 기반 bad-pixel map + 최소 면적/PSF gate | 추적 중 같은 위치라는 이유만으로 별을 bad pixel로 등록하지 않음 |
| cosmic ray·전자 spike | 매우 날카롭거나 비정상 형상 | PSF 폭, 연결 면적, 이심률 gate | 원본 patch 검증 없이 후보를 solver에 전달하지 않음 |
| 흔들림·별 trail | 방향성을 가진 길쭉한 PSF | 다중 scale/이심률과 IMU exposure-motion 연계 | 짧은 trail은 별 후보로 보존하고 centroid covariance를 크게 설정 |

구름은 단순한 가산 noise만이 아니다. 별빛을 곱셈적으로 감쇠하거나 완전히 차단하므로 “구름을
제거해 원래 별을 되살린다”는 목표는 물리적으로 성립하지 않는다. 목표는 구름 glow를 제거하고
그 프레임에서 실제로 관측 가능한 별의 SNR을 정확히 평가하는 것이다.

## 4. 블록 다이어그램

~~~mermaid
flowchart LR
    RAW["12/10-bit RAW view<br/>복사 없음"] --> CAL["black/dark 보정<br/>static bad-pixel mask"]
    CAL --> QM["Coarse QualityMap<br/>median / MAD / saturation / gradient"]
    QM --> PLAN{"탐색 planner"}
    PLAN -->|"16 mm: 중앙 우선"| CENTER["중앙 ROI"]
    PLAN -->|"6 mm 또는 중앙 불량"| RING["품질 상위 주변 tile"]
    CENTER --> PRE["B, sigma, M 보간<br/>line/tile 단위"]
    RING --> PRE
    PRE --> NORM["Z = (I-B)/sigma<br/>scratch row만 사용"]
    NORM --> PSF["separable PSF/DoG bank<br/>radial scale profile"]
    PSF --> MAX["local maxima + NMS"]
    MAX --> FIT["원본 RAW 5x5/7x7<br/>centroid / FWHM / shape"]
    FIT --> STAR["공간적으로 분산된 StarSet"]
    STAR --> ENOUGH{"solver에 충분한가?"}
    ENOUGH -->|"예"| SOLVE["solver adapter"]
    ENOUGH -->|"아니오"| PLAN
    QM -->|"관측 불가"| FAIL["NO_USABLE_SKY"]
~~~

`QualityMap`은 중앙·주변에서 한 번만 만든다. detector tile은 겹치지 않으며 filter에 필요한
6~12 pixel halo만 읽는다. 후보 소유권은 tile interior에만 두어 겹친 solver crop 때문에 같은
픽셀을 다시 검출하지 않는다.

## 5. 프레임 작업 순서도

~~~mermaid
flowchart TD
    A["새 RAW sequence claim"] --> B["profile/stride/bit depth 검증"]
    B --> C["coarse block 통계와 포화 component 계산"]
    C --> D{"유효 하늘이 있는가?"}
    D -->|"아니오"| X["명시적 실패 + 진단 기록"]
    D -->|"예"| E["중앙 ROI 또는 첫 radial probe 선택"]
    E --> F["background/noise/mask를 row 단위 보간"]
    F --> G["정규화 + PSF filter + local maximum"]
    G --> H["원본 patch centroid/형상 검증"]
    H --> I["중복 제거와 공간 quota 적용"]
    I --> J{"수와 공간 분포가 충분한가?"}
    J -->|"예"| K["StarSet 반환 후 solver"]
    J -->|"아니오, 예산 남음"| L["다음 품질 상위 주변 tile"]
    L --> F
    J -->|"아니오, 예산 소진"| M["INSUFFICIENT_STARS"]
~~~

중앙 ROI가 달이나 조명으로 불량이어도 프레임 전체를 실패시키지 않는다. 6 mm profile은 시작
단계부터 center/mid/edge radial zone의 최소 probe 수를 지정해 가장자리 별만 보이는 장면을
탐색한다. 16 mm profile은 중앙에서 충분한 별과 공간 분포를 얻으면 조기 종료한다.

## 6. 권장 전처리 알고리즘

### 6.1 검출용 수식

각 mesh에서 masked pixel을 제외한 robust median 또는 sigma-clipped mean을 `B_ij`,
`1.4826 * MAD`를 기본 잡음 `sigma_ij`로 구한다. 불량 mesh는 유효 이웃에서 채우되 별도의
invalid flag를 남긴다. 작은 grid를 bilinear 또는 bicubic 보간해 각 pixel의 값을 얻는다.

`Z(x,y) = (I(x,y) - B(x,y)) / max(sigma(x,y), sigma_floor)`

각 렌즈 radial zone의 예상 PSF scale `s`에 대해 다음 응답을 계산한다.

`R_s(x,y) = Z(x,y) * K_s`

`K_s`는 Gaussian 형태의 matched filter 또는 넓은 Gaussian을 뺀 zero-sum DoG로 한다.
2~3개의 scale만 두고 x/y separable convolution으로 구현한다. DoG는 mesh 보간 뒤 남은 완만한
배경에 더 둔감하고, matched filter는 noise가 잘 정규화된 장면에서 SNR이 좋다. 둘을 corpus에서
같은 입력으로 비교해 한 기본값을 정한다.

최종 중심은 `R_s`의 pixel 좌표가 아니라 원본 RAW의 5x5 또는 7x7 patch에서 robust weighted
centroid나 작은 PSF fit으로 계산한다. 전처리 영상은 후보 생성에만 사용한다.

### 6.2 방법 비교

| 방법 | 연산량 | 장점 | 위험 | 결정 |
| --- | ---: | --- | --- | --- |
| mesh robust background + local MAD/RMS | 낮음 | 광해·구름 glow·비네팅에 직접 대응, 설명 가능 | mesh 크기 조정 필요 | 기본 채택 |
| separable matched filter bank | 매우 낮음 | 별 PSF의 SNR을 최대로 활용 | 렌즈/반경별 PSF scale 필요 | 기본 채택 |
| DoG/LoG | 낮음 | 저주파 잔여 배경 억제, 점원 강조 | 아주 흐린 별이나 trail 손실 가능 | matched filter와 A/B |
| white top-hat/rolling ball | 낮음~중간 | 구현이 단순하고 빠른 background fallback | kernel 경계·halo ringing, 큰 별 flux 손상 | QualityMap/fallback만 |
| wavelet multiscale | 중간~높음 | scale 분리가 정교함 | 메모리와 여러 pass, parameter 증가 | 초기 보류 |
| CLAHE/Retinex | 중간 | 사람 눈에는 contrast 개선 | noise·halo도 강화하고 flux 의미가 바뀜 | solver 경로 금지 |
| BM3D/NLM | 높음 | 일반 영상 denoise 성능 | 점광원을 noise로 지울 수 있음 | 금지 |
| AI denoise/super-resolution | 매우 높음 | 특정 학습 분포에서는 보기 좋은 복원 | 별 hallucination/삭제, 학습·검증 비용 | solver 입력 금지 |

## 7. 구현 선택

### 7.1 1단계: SEP C API를 직접 연결

가장 짧고 위험이 낮은 경로는 검증된 SEP 알고리즘을 유지하면서 Python wrapper와 전체 배열
복사를 제거하는 것이다.

- `libsep.so`를 `libpifinder_detect.so`에서 동적 연결한다.
- RAW에서 2x2 binned `float32` 또는 native `int` 작업 평면 하나만 만든다.
- `sep_background()`으로 작은 background/noise spline grid를 한 번 만든다.
- `sep_bkg_subline()`과 `sep_bkg_rmsline()`으로 필요한 row만 계산한다.
- custom row ring buffer에서 정규화와 separable filter, local maximum을 연속 처리한다.
- source measurement는 필요한 후보 patch만 자체 centroid/shape 코드로 처리한다.
- scratch buffer와 background grid를 context에 보관해 다음 frame에 재사용한다.

SEP C API가 직접 지원하는 영상 element type은 byte, native int, float, double이며 uint16 전용
type은 없다. 따라서 SEP 단계에서는 compact binned 작업 평면 하나가 필요하다. 다만 background와
RMS를 한 줄씩 평가하는 API를 공개하므로 `sep_detect.py`처럼 full-frame background, RMS,
background-subtracted 배열 세 개를 추가로 만들 필요는 없다. 실제 속도 우위는 Pi 4/Pi 5
benchmark로 확인해야 하며 추정치를 완료 성능으로 기록하지 않는다.

SEP 전체 라이브러리는 LGPLv3이다. 사용자가 허용한 범위이며 상업 배포가 가능하지만 저작권·
라이선스 고지, LGPL 소스 제공/수정 공개와 사용자가 해당 라이브러리를 교체·재링크할 권리 등
배포 의무를 확인해야 한다. 제품 결합 부담을 줄이려면 동적 연결을 기본으로 한다. 이 문서는
법률 자문을 대신하지 않는다.

### 7.2 2단계: 독립 native C++ core

SEP C prototype이 기준 corpus에서 정확도와 속도를 입증한 뒤에만 독립 구현 여부를 결정한다.
이득이 작으면 SEP를 유지하는 편이 개발·회귀 비용이 낮다. 독립 core를 만들 경우:

- 공개 API나 source를 복사하지 않고 본 문서의 입력/출력·수학 명세로 구현한다.
- uint16 RAW view, 작은 background grid, 3~7 row float scratch만 유지한다.
- scalar reference와 ARM NEON path의 후보·centroid 오차를 golden corpus로 비교한다.
- lens profile에 mesh 크기, PSF scale, radial validity, halo dilation을 넣는다.
- detector와 solver가 같은 `QualityMap`과 `StarSet`을 공유해 재검출을 없앤다.

핵심에는 OpenCV가 필수는 아니다. 작은 binary와 예측 가능한 메모리가 우선이면 직접 separable
filter와 morphology를 구현한다. 빠른 prototype 또는 이미 OpenCV를 포함하는 build라면
`sepFilter2D`, Gaussian, morphology를 쓸 수 있고 OpenCV 4.5 이상은 Apache-2.0이다.

### 7.3 Python과 daemon

기본은 in-process C ABI 또는 얇은 pybind11/ctypes binding이다. Python은 설정과 결과 구조만
다루고 RAW NumPy 변환·복사를 하지 않는다. detector crash 격리나 독립 업데이트 요구가 실제로
생길 때만 daemon을 추가한다. daemon을 써도 RAW는 Unix socket으로 복사하지 않고 shared-memory
slot descriptor만 전달한다.

## 8. AI는 어디에 최소한으로 쓸 수 있는가

고전 전처리의 오류 corpus가 충분히 쌓인 뒤에도 특정 artifact가 반복되면 full-frame detector가
아니라 다음 작은 분류기 하나만 검토한다.

`입력: 64x64 또는 96x96 tile thumbnail + QualityMap channel`

`출력: USABLE_SKY / CLOUD_OR_GLOW / GLARE_OR_GHOST / GROUND_OR_OBSTRUCTION`

이 모델은 별 좌표를 생성하지 않고 tile 처리 순서나 제외 여부만 보조한다. label은 solver 성공,
검출 후보 형상 통계, 포화 비율로 weak label을 만들고 애매한 표본만 사람이 확인할 수 있어
end-to-end 별 mask보다 자료 구축 비용이 작다. AI 판단 하나로 전체 프레임을 버리지 않고 최소
주변 probe를 유지한다.

| 추론기 | 라이선스 | PiFinder에서의 위치 |
| --- | --- | --- |
| ncnn | BSD-3-Clause | ARM NEON, 작은 runtime, INT8 tile classifier의 첫 후보 |
| OpenCV DNN | Apache-2.0 계열(OpenCV 4.5+) | OpenCV가 이미 포함될 때 추가 dependency 없이 사용 |
| ONNX Runtime | MIT | 모델 호환성과 여러 backend가 더 중요할 때 사용; package 크기 측정 필요 |
| TensorFlow Lite/Coral | Apache-2.0 계열 | Coral 또는 지원 NPU를 제품 사양으로 둘 때만 선택 |

모델 코드뿐 아니라 pretrained weight와 training data의 라이선스도 별도로 검토한다. 직접 학습한
weight만 배포하는 것을 기본 정책으로 한다.

## 9. 단계별 작업 계획

### Phase A — 측정 가능한 baseline

1. 현재 SEP Python 결과에 frame sequence, lens, radial zone, 후보 거절 사유를 기록한다.
2. 같은 RAW corpus에서 detector recall, false candidate, solver success, false solve, P50/P95 시간,
   peak RSS를 측정한다.
3. 중앙만 좋은 장면뿐 아니라 달이 중앙에 있고 6 mm 가장자리 별만 보이는 장면을 포함한다.

### Phase B — C streaming prototype

1. `libsep.so` 동적 연결, read-only uint16 frame view, compact binned 작업 평면 하나를 구현한다.
2. QualityMap을 한 번 계산하고 center → peripheral tile이 공유하게 한다.
3. row background/RMS, separable filter, local maximum, RAW centroid를 연결한다.
4. Python SEP와 동일 후보가 아니라 **동일 solver 결과와 더 나은 지연**을 수락 기준으로 삼는다.

### Phase C — 렌즈와 환경 보정

1. 16 mm와 6 mm의 center/mid/edge PSF scale과 valid circle을 측정한다.
2. 달·가로등 위치, 박무, 얇은/두꺼운 구름, 이슬, defocus, motion별 threshold를 hold-out에서 검증한다.
3. full-frame pixel 재처리 없이 주변 tile을 추가하는 early-exit planner를 검증한다.

### Phase D — AI 필요성 결정

1. 오검출을 원인별로 집계한다.
2. 고전 mask/shape/QualityMap 조정으로 해결되지 않는 반복 유형이 충분한지 확인한다.
3. 있을 때만 tiny tile classifier를 native-only 경로와 shadow 비교한다.
4. solver 성공률 또는 false solve가 유의하게 개선되지 않으면 모델을 제품에 넣지 않는다.

## 10. 수락 기준

속도만 개선하면 희미한 별을 잃을 수 있으므로 다음을 같은 corpus에서 함께 gate한다.

- 관측 가능한 solver-matched star recall과 false candidate/frame
- 6 mm radial zone별 recall과 최소 공간 분포
- 달·가로등·두꺼운 구름에서 false solve가 발생하지 않는지
- solver success rate, inlier 수, residual, 명시적 실패의 정확성
- Pi 4/Pi 5의 center, center+periphery, full sweep P50/P95와 peak RSS
- Python 배열 복사량, C scratch 크기, deadline 초과 frame 수

절대 시간 목표는 측정 전 확정하지 않는다. 첫 merge gate는 같은 장비·RAW에서 Python SEP 대비
solver 성공률을 낮추지 않으면서 P95 detector 시간과 peak memory를 의미 있게 줄이는 것이다.

## 11. 라이선스와 참고 자료

| 구성요소 | 확인된 조건 | 사용 결정 |
| --- | --- | --- |
| SEP | C core 포함 전체 LGPLv3; C core는 표준 라이브러리 외 runtime dependency 없음 | 동적 연결 prototype 허용 |
| OpenCV 4.5+ | Apache-2.0 | 선택적 prototype/기존 dependency일 때 허용 |
| ncnn | BSD-3-Clause | 선택적 tiny AI runtime 허용 |
| ONNX Runtime | MIT | 선택적 AI runtime 허용 |

- [SEP 공식 저장소와 라이선스](https://github.com/sep-developers/sep)
- [SEP C API: background, line interpolation, extraction](https://github.com/sep-developers/sep/blob/main/src/sep.h)
- [SEP Python API 문서](https://sep.readthedocs.io/en/stable/reference.html)
- [Photutils Background2D 알고리즘 참고](https://photutils.readthedocs.io/en/stable/api/photutils.background.Background2D.html)
- [OpenCV 라이선스](https://opencv.org/license/)
- [OpenCV image filter API](https://docs.opencv.org/4.x/d4/d86/group__imgproc__filter.html)
- [ncnn 공식 저장소](https://github.com/Tencent/ncnn)
- [ONNX Runtime 공식 저장소](https://github.com/microsoft/onnxruntime)
- [TensorFlow/TFLite 공식 저장소](https://github.com/tensorflow/tensorflow)
- [경량 CNN 별 검출·centroid 연구와 Pi/Coral 측정](https://arxiv.org/html/2404.19108v2)
