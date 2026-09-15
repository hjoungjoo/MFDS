# PiFinder AI 기반 별 검출 조사 및 적용 설계

> 작성일: 2026-08-25
> 범위: 달·도시 광해·렌즈 flare·센서 잡음 때문에 별 검출이 어려운 상황에서, PiFinder의 전용 native detector에 AI를 안전하게 결합하는 방법을 조사하고 설계한다.
> 선행 문서: [전용 native detector 설계](mf_native_detector_design_ko.md)

> **2026-08-25 우선순위 수정:** 이 문서는 AI가 필요하다고 실증된 이후의 선택지를 다룬다.
> 현재 구현의 기준 결정은 [고속 하늘 전처리 설계](mf_fast_sky_preprocessing_design_ko.md)이며,
> full-frame AI 대신 robust background/noise/mask와 PSF filter를 먼저 구현한다.

## 1. 결론

**AI를 사용한 고정밀·고속 별 검출 기법은 실제로 있다.** 가장 직접적인 계열은 일반 물체 검출기(YOLO 등)가 아니라, 경량 encoder-decoder CNN이 다음을 한 번에 추론하는 방식이다.

1. 별 픽셀 또는 별 중심의 확률 지도
2. 각 별의 sub-pixel 중심까지의 거리 지도, 또는 X/Y offset 지도
3. 필요할 때 artifact 또는 usable-sky 지도

실제 별 추적기·지상 관측 연구에서 이 계열은 센서 열잡음, 달·flare, 저 SNR, motion blur에 대해 고전 임계값 방식보다 높은 재현율과 centroid 정확도를 보고했다. 그러나 **PiFinder의 기본 경로를 full-frame AI 하나로 교체하는 것은 권하지 않는다.**

- 현재 공개된 Raspberry Pi 실측은 Pi 4B + Coral TPU에서 640x480 MobileUNet이 평균 265.5 ms, 3.77 Hz였다. 이는 full-frame을 매 프레임 처리하는 PiFinder 기본 경로의 지연 예산에는 크다.
- 6 mm 광각의 주변부 PSF, 비네팅, 코마와 16 mm의 중심부 조건은 학습 분포가 크게 다르다. 다른 카메라의 논문 모델을 바로 쓰면 일반화와 라이선스 양쪽에서 문제가 생긴다.
- AI가 포화된 달 주변이나 no-sky 프레임에서 그럴듯한 점광원을 만들어 내면 solver의 false solve 위험이 커진다.

따라서 AI를 도입하는 경우의 제품 원칙은 다음이다.

> C++ native detector가 항상 후보와 raw-pixel centroid를 만들고, AI는 애매한 후보의 오검출을 줄이며 solver 실패 또는 심한 광해 때 선택한 타일의 희미한 별을 구조하는 보조기다.

이 설계는 AI가 없거나, 모델이 맞지 않거나, 추론 deadline을 넘을 때도 기존 detector가 그대로 관측을 계속할 수 있게 한다.

## 2. 조사 결과

| 사례 | 방식 | 보고된 근거 | PiFinder 판단 |
|---|---|---|---|
| Zhao et al., IEEE TAES 2025 | MobileUNet/ELUNet이 별 mask와 centroid distance map을 함께 출력한 뒤, 국소 최소제곱 삼변측량으로 중심 산출 | 잡광 합성에서 ELUNet F1 97.3%, centroid RMSE 0.1348 px. 실제 야간·달·flare 시험. Pi 4B + USB Coral에서 INT8 MobileUNet 265.5 ms, 3.77 Hz | 가장 가까운 직접 근거. full-frame 기본값이 아니라 타일 rescue 모델의 설계 기준으로 채택 |
| Huang et al., Optics Continuum 2026 | 물리 PSF·회절·Zernike 수차·defocus와 실측 dark noise를 섞고, mask + X offset + Y offset을 동시 예측하는 DA-MobileUNet | 합성 F1 98.02%, 실제 in-focus 0.17 px, 심한 defocus 0.23 px. RK3588 NPU INT8에서 512² 45.28 ms, 1024² 175.07 ms | 6/16 mm 렌즈 수차를 학습에 넣는 방법과 3-head 출력의 가장 좋은 clean-room 설계 근거 |
| ATD-DL, Frontiers 2026 | 16-bit HDR 입력을 tile background subtraction과 adaptive stretch로 정규화한 뒤, 다중 스케일 U-Net으로 희미한 점광원 분할 | 실제 wide-field 저 SNR 자료에서 희미한 점광원 재현율 향상을 보고. RTX 4060 Ti에서 약 50 ms/frame | 중앙 우선·주변 타일, tile별 배경 추정, 16-bit 전처리의 근거. Pi 성능 근거는 아님 |
| AutoSourceID-Light, 2022 | U-Net source segmentation 뒤 LoG로 위치화 | Apache-2.0 공개 코드와 모델 학습 경로가 있음 | 상업적으로 재사용 가능한 연구 baseline. Python/TensorFlow 구현과 학습 도메인은 PiFinder용 native 경로로 직접 쓰지 않음 |
| SpaceDevEngineer TESS Star Tracker | U-Net/HRNet 검출 + 왜곡 보정 + 기하 solver + no-solution quality gate | 실제 TESS 영상에서 104/107 solve, detector centroid median 약 4.6 arcsec 보고 | MIT 코드. SIP 왜곡 보정과 false lock 거절 검증의 참고용이며, RANSAC solver 지연이 수초~수분이라 실시간 detector로는 부적합 |

### 2.1 가장 중요한 직접 사례: mask + distance map + 삼변측량

Zhao 연구는 noisy star image를 경량 U-Net에 넣어 별/배경 segmentation map과 각 픽셀에서 가까운 별 중심까지의 distance map을 동시에 만든다. 별로 분류된 작은 5x5 영역의 distance 값을 이용해 least-squares trilateration으로 sub-pixel centroid를 푼다.

이 방식의 강점은 다음과 같다.

- 검출과 중심점 계산을 서로 다른 CNN 또는 threshold 조합으로 나누지 않는다.
- 합성된 깨끗한 별 영상에 실제 카메라 dark frame과 여러 각도의 stray-light frame을 합성해, sensor-specific noise를 학습에 반영했다.
- 640x480, 16 mm 카메라의 hardware-in-the-loop 및 실제 야간 시험까지 수행했다.
- 달 또는 강한 flare가 포함된 야간 시험에서 고전 임계값 모델보다 더 안정적인 검출·식별 결과를 제시했다.

한계도 명확하다.

- Pi 4B 단독이 아니라 USB Coral Edge TPU를 사용했다.
- MobileUNet INT8의 265.5 ms 결과는 640x480 한 장의 추론 결과다. PiFinder의 1920x1080 RAW 또는 6 mm 전 영역에 선형으로 외삽하면 안 된다.
- 논문의 공개 GitHub 저장소에는 명시적인 LICENSE 파일이 없다. 코드, pretrained weight, 내려받는 학습·시험 데이터는 제품에 복사하지 않는다.

### 2.2 PiFinder 렌즈에 특히 유용한 최신 방향: mask + dx + dy

Huang 연구는 Gaussian 하나로 PSF를 근사하는 대신 scalar diffraction 및 Zernike 계수로 수차·defocus를 바꾼 물리 합성 자료와 실제 dark noise를 결합했다. 모델은 별 mask뿐 아니라 각 픽셀의 sub-pixel X/Y offset을 함께 예측하고, connected component 안의 confidence-weighted fusion으로 centroid를 낸다.

PiFinder에는 distance map보다 이 3-head 구성이 더 단순한 실험 출발점이다.

- output 1: star probability 또는 center heatmap
- output 2: local dx
- output 3: local dy

다만 이 논문은 구현과 weights의 재사용 가능한 공개 라이선스를 찾지 못했다. 구조, 시험 방법, 물리 합성의 원칙만 참고해 자체 코드와 자체 데이터를 사용한다.

### 2.3 저 SNR wide-field에서 얻을 점

ATD-DL은 16-bit 광학 wide-field 프레임을 전체 축소하지 않고, dark/background 보정 후 512² 수준의 subfield로 나눠 처리한다. 이는 PiFinder가 검토 중인 중앙 우선·주변 타일 방식과 직접 맞닿아 있다.

특히 다음은 AI 유무와 상관없이 native detector에도 반영할 가치가 있다.

- 16-bit RAW의 global 8-bit normalize는 faint star contrast를 잃기 쉽다.
- tile median/MAD 기반 background model을 먼저 빼야 광해 gradient와 희미한 별을 분리하기 쉽다.
- image resize로 작은 점광원을 없애지 말고, native pixel 좌표를 유지한 tile만 처리해야 한다.

### 2.4 패치 기반 sub-pixel 회귀도 유망하다

대형 full-frame network 대신, 이미 native detector가 찾은 후보의 24x24~48x48 patch에만 작은 CNN을 적용하는 연구도 있다. CoordConv 또는 capsule/coordinate regression 계열은 별 위치 offset을 직접 회귀한다.

이 계열은 PiFinder에서는 다음 용도로만 고려한다.

- hot pixel, flare halo, trail, cloud texture를 별과 구별하는 분류
- 후보의 우선순위와 confidence 보정
- 선택적으로 dx/dy hint 제공

최종 centroid는 raw-pixel PSF fit 또는 native Gaussian/weighted centroid가 확정한다. 이렇게 하면 INT8 양자화 오차와 domain shift가 solver에 미치는 영향을 제한할 수 있다.

## 3. PiFinder 적용 결정

### 채택

1. C++ native detector가 full frame 또는 계획된 tile에서 후보를 생성한다.
2. 작은 AI PatchNet이 애매한 후보만 batch 처리한다.
3. solver 실패 또는 quality map이 나쁜 경우에만 TinyTileNet을 선택한 중심/주변 tile에 실행한다.
4. TinyTileNet의 새 후보도 반드시 raw image에서 PSF fit, 형상 검증, solver inlier 검증을 거친다.
5. 모델·렌즈 profile·runtime이 맞지 않으면 AI를 끄고 native-only로 즉시 fallback한다.

### 보류

- 매 프레임 1920x1080 full-frame U-Net 실행
- AI denoise 또는 super-resolution 결과를 solver 입력으로 직접 사용
- AI confidence만으로 좌표를 publish
- 별 수가 많다는 이유만으로 quality gate를 통과시키는 방식

## 4. 블록 다이어그램

~~~mermaid
flowchart LR
    RAW["12/10-bit RAW<br/>shared-memory slot"] --> Q["C++ QualityMap<br/>background / RMS / saturation / glare / valid-mask"]
    Q --> PLAN["중앙 우선 planner<br/>중앙 ROI → 주변 ring tile → 전체 valid tile"]
    PLAN --> NATIVE["NEON native detector<br/>matched filter / local maxima / component"]
    NATIVE --> FIT["RAW PSF fit<br/>centroid / covariance / FWHM / chi2"]

    FIT --> DECIDE{"강한 물리 후보인가?"}
    DECIDE -- "예" --> STARSET["StarSet 후보"]
    DECIDE -- "애매함" --> PATCH["PF-AssistNet<br/>candidate patch batch"]
    PATCH --> GATE["ML + raw PSF + mask<br/>결합 safety gate"]
    GATE --> STARSET

    STARSET --> SOLVE["tetra3 또는 향후 solver<br/>geometric verification"]
    SOLVE -- "성공" --> OUT["검증된 좌표 발행"]
    SOLVE -- "실패 + 난이도 높음" --> TILE["PF-RescueNet<br/>선택된 1..N tile만"]
    TILE --> FIT
    SOLVE -- "무별 / 불량 sky" --> DEG["NO_USABLE_SKY<br/>명시적 실패"]
~~~

AI는 모든 후보를 만들거나 solver를 대체하지 않는다. native detector와 solver가 각각 관측 물리와 기하학적 일관성을 보증하고, AI는 환경적으로 어려운 장면에서 후보의 품질을 높인다.

## 5. 작업 순서도

~~~mermaid
flowchart TD
    A["Frame 수신"] --> B["렌즈 profile / model fingerprint 검증"]
    B -->|불일치 또는 AI unavailable| C["native-only 검출"]
    B -->|일치| D["QualityMap 및 중앙 ROI 평가"]
    D --> E["native 후보 추출 + RAW PSF fit"]
    E --> F{"후보 품질/개수가 충분한가?"}
    F -->|예| G["애매 후보만 PatchNet batch 처리"]
    F -->|아니오| H["중앙·주변 tile의 품질 순위화"]
    H --> I["우선 tile에서 RescueNet 실행"]
    I --> J["Rescue 후보를 RAW PSF fit로 재검증"]
    G --> K["candidate merge / tile de-dup / StarSet"]
    J --> K
    K --> L["solver + residual / inlier / spread quality gate"]
    L -->|통과| M["좌표 publish, provenance 기록"]
    L -->|실패 & 남은 budget 있음| H
    L -->|실패 또는 budget 초과| N["native 결과 또는 NO_USABLE_SKY 반환"]
    C --> K
~~~

### 5.1 deadline 규칙

- Capture deadline을 AI가 점유하지 않는다. 프레임 slot은 이미 준비된 최신 frame만 사용한다.
- PatchNet은 최대 후보 수와 최대 batch 수를 둔다. 초과 후보는 native score 순으로 남긴다.
- RescueNet은 planner가 선정한 제한된 tile만 실행한다. full valid tile을 AI로 모두 훑지 않는다.
- model load, cold start, memory allocation은 관측 루프 밖에서 한 번만 수행한다.
- timeout, thermal throttling, accelerator 오류 시 해당 frame은 partial AI 결과를 신뢰하지 않고 native-only 규칙으로 처리한다.

## 6. 두 단계 모델 설계

| 모델 | 범위 | 입력 | 출력 | 도입 순서 |
|---|---|---|---|---|
| PF-AssistNet | native detector의 애매 후보만 | 32x32 또는 48x48 native-pixel residual patch, context patch, valid/saturation mask, local SNR/FWHM/radial zone | p_star, artifact class, calibrated confidence, 선택적 dx/dy hint | 1차 |
| PF-RescueNet | solver 실패 때 quality 상위 1..N tile | 256² 또는 512² RAW-normalized tile, mask, radial coordinate | center heatmap 또는 mask, dx/dy, artifact/usable-sky map | 2차 |
| Full-frame multi-task net | 전체 sensor frame | 전체 RAW | dense mask/offset | 연구용 shadow mode만 |

### 6.1 PF-AssistNet

PF-AssistNet은 depthwise-separable convolution 또는 비슷한 작은 C++ 추론 친화 모델로 한다. 입력은 이미지 전체의 8-bit 사본이 아니라 이미 검출한 후보 주변의 native RAW residual이다.

입력 채널 예시는 다음과 같다.

1. local background를 뺀 intensity patch
2. robust RMS로 나눈 normalized patch
3. matched-filter response patch
4. saturation/invalid/glare mask
5. 2x downsample context patch
6. 렌즈 profile의 radial zone, local expected FWHM, exposure/gain 같은 작은 metadata

분류 class는 최소한 다음을 포함한다.

~~~text
star
hot_pixel_or_fixed_pattern
halo_or_glare_edge
trail_or_elongated_source
cloud_or_background_texture
merged_or_ambiguous
unknown
~~~

AI는 강한 native 후보를 낮은 confidence 하나로 제거하지 않는다. native PSF 품질이 좋은 별은 보존하고, AI 결과는 후보 순위·solver 투입 수·애매한 component의 거절에 우선 사용한다.

### 6.2 PF-RescueNet

PF-RescueNet은 Zhao식 distance-map 또는 Huang식 mask + dx + dy로 시작할 수 있다. PiFinder용 첫 구현에는 후처리가 단순한 다음 3-head 구성을 권장한다.

~~~text
head 0: star-center probability / segmentation
head 1: local sub-pixel dx
head 2: local sub-pixel dy
optional head: artifact 또는 usable-sky probability
~~~

처리 규칙은 다음과 같다.

1. head 0의 local maximum 또는 connected component를 AI candidate로 만든다.
2. dx/dy는 coarse position의 hint로만 사용한다.
3. 원본 RAW에서 native PSF fit를 수행해 final centroid, covariance, chi2를 만든다.
4. saturation, glare mask, shape, minimum SNR, tile ownership을 다시 적용한다.
5. solver의 inlier와 residual 검증을 통과한 점만 최종 해에 기여시킨다.

이 순서는 AI가 본 적 없는 달 halo나 광학 ghost에서 star-like response를 낼 수 있는 위험을 줄인다.

## 7. 6 mm와 16 mm 렌즈 적용 원칙

모델 하나를 두 렌즈에 강제 적용하지 않는다. 최소한 렌즈 profile과 radial zone을 분리한다.

| 조건 | 16 mm | 6 mm 광각 |
|---|---|---|
| 일반 우선순위 | 중앙 ROI의 정상 별 | 주변 ring tile의 별 수와 quality가 더 중요할 수 있음 |
| 광해 위험 | 중앙 달/가로등 영향 | 중심 glare 외에 주변 코마·비네팅·ghost가 증가 |
| 모델 사용 | AssistNet 우선 | AssistNet + 주변 tile RescueNet 우선 |
| centroid 좌표 | RAW pixel에서 측정 후 distortion transform | 동일. 전체 frame rectification은 하지 않음 |
| profile 분리 | center/mid/edge PSF | center/mid/edge를 더 세분화하고, lens별 model fingerprint 검사 |

새 렌즈 또는 calibration되지 않은 profile에서는 AI를 기본 비활성화한다. 이 경우에도 native detector와 tile planner만으로 관측이 가능해야 한다.

## 8. 학습 데이터 설계

AI 성능은 network 이름보다 data provenance와 환경 분포에 크게 좌우된다. 자체 자료 기반의 학습 세트가 안전하고 재현 가능하다.

### 8.1 데이터 구성

1. **자체 RAW nuisance frame**
   - lens cap dark, hot pixel, read noise, fixed pattern
   - 달·가로등·도시 광해·lens flare
   - 박무, 얇은 구름, 이슬, 초점 이탈, 흔들림, trail
   - 완전 포화·무별·건물/나무/지평선 같은 hard negative
2. **렌즈별 측정 PSF를 넣은 물리 합성**
   - 6 mm/16 mm, center/mid/edge별 PSF
   - sub-pixel random position, brightness, background, gain, exposure
   - defocus, astigmatism, coma, motion elongation을 범위화
   - 실제 nuisance RAW 위에 합성해 sensor와 stray-light 분포를 유지
3. **고신뢰 실제 하늘 frame**
   - 충분한 inlier와 낮은 residual의 solve 결과를 초벌 label로 사용
   - 달·flare·가장자리·희미한 별은 수동 검수
   - native/AI 불일치 샘플을 active-learning queue에 넣어 재검수

별 검출 모델의 label은 별의 catalog ID가 아니라 pixel 위치와 PSF morphology다. 그러므로 무작위 합성 점광원과 자체 측정 PSF만으로도 초벌 학습을 시작할 수 있다. 상업 배포용 model을 만들면서 특정 천체 카탈로그를 사용한다면, 카탈로그·파생 데이터·weights 각각의 권리를 별도로 검토한다.

### 8.2 반드시 분리할 축

- camera sensor, bit depth, gain, exposure, sensor temperature
- lens 6 mm / 16 mm, center/mid/edge radial zone
- 달·가로등 위치, saturation, bloom, flare 방향
- 도시 광해, 박무, cloud, dew
- focus, vibration, push-to motion, star trail
- no-star와 no-usable-sky frame

train/validation/test 분할은 crop 단위가 아니라 **밤·장소·카메라·렌즈 세션 단위**로 한다. 같은 원본 frame의 crop·flip·noise augmentation이 train과 test에 동시에 들어가면 성능이 과대평가된다.

## 9. C/C++ 런타임과 Python 연동

### 9.1 프로세스 경계

기본 경로는 native detector와 AI inference를 같은 C++ process에 둔다. Python은 frame 대용량 tensor를 만들거나 복사하지 않고, configuration·상태 전이·solver adapter 역할을 유지한다.

~~~text
libpifinder_detect.so
  항상 존재:
    QualityMap, tile planner, matched filter, PSF fit, StarSet

libpifinder_detect_ml.so
  선택 로드:
    model session, PatchNet, RescueNet, inference backend
~~~

데몬은 여러 프로세스가 같은 NPU를 공유하거나 model hot-reload가 필요한 경우에만 선택한다. frame마다 gRPC/JSON/PNG를 넘기는 구조는 피한다.

### 9.2 ABI 개념

~~~text
pf_ml_session_create(model_manifest, lens_profile, runtime_options)
pf_ml_classify_candidate_batch(patch_views[], verdicts[])
pf_ml_detect_rescue_tile(tile_view, ml_candidates[])
pf_ml_session_health()
~~~

각 결과에는 최소한 다음 trace 정보를 기록한다.

~~~text
model_id
model_sha256
model_license
lens_profile_fingerprint
runtime_backend
p_star / artifact_class / calibrated_confidence
timeout_or_ood_flag
decision provenance: classical | ml_assisted | ml_rescued
~~~

model SHA-256 또는 lens profile fingerprint가 맞지 않으면 모델을 로드하지 않고 native-only로 시작한다.

### 9.3 상업 사용 가능한 inference 후보

| 구성요소 | 라이선스 | 권장 역할 |
|---|---|---|
| ncnn | BSD-3-Clause, 단 번들 third-party notice 검토 | Pi ARM NEON과 INT8 위주의 기본 C++ inference 후보 |
| ONNX Runtime | MIT | PC/서버와 ARM의 공통 ONNX fallback |
| TensorFlow Lite | Apache-2.0 | TFLite/Coral 사용 시 선택 backend |
| OpenCV | Apache-2.0 | mask, distortion, morphology 및 보조 구현 |

모델은 ONNX를 canonical export로 두고, 기기별 backend artifact는 build 과정에서 만든다. post-training quantization만으로 충분하다고 가정하지 않는다. Zhao 연구도 단순 PTQ에서 성능 저하를 관찰했으므로, 제품 모델은 float baseline과 INT8 QAT 결과를 같은 hold-out corpus에서 비교해야 한다.

## 10. 안전 규칙과 수락 기준

### 10.1 안전 규칙

1. ML runtime 없음, model/profile mismatch, inference timeout, memory 부족이면 즉시 native-only로 fallback한다.
2. AI가 높은 star probability를 내도 native RAW PSF fit의 SNR, chi2, eccentricity, mask, saturation 조건을 통과하지 못하면 버린다.
3. 강한 native 후보는 AI score만으로 즉시 삭제하지 않는다.
4. ML rescue 후보는 minimum inlier, solver residual, spatial spread, 직전 solve 일관성 검증을 모두 통과해야 publish한다.
5. budget 초과 tile은 정상 StarSet으로 위장하지 않고 ML_BUDGET_EXCEEDED를 기록한다.
6. no-star/no-usable-sky 상황을 모델이 별로 채우지 않도록 hard negative와 explicit abstain 결과를 둔다.

### 10.2 수락 지표

| 범주 | 지표 |
|---|---|
| 검출 | SNR·radial zone·환경별 precision/recall, false positive per megapixel |
| centroid | native pixel RMSE, bias, repeatability, covariance calibration |
| 광각 | distortion 변환 후 hold-out astrometric residual |
| solve | solve success rate, false-solve rate, inlier 수, residual, RA/Dec/Roll 안정성 |
| 성능 | Pi 4/Pi 5 P50/P95/P99, cold/warm start, CPU/RSS, NPU/USB 오류, thermal throttling |
| 안전 | moon/glare, no-star, wrong lens profile, model missing, daemon restart, timeout에서 native baseline보다 false solve가 증가하지 않음 |

AI 도입 성공은 F1만 높아지는 것이 아니라, **동일한 시간 예산에서 true solve는 늘고 false solve는 늘지 않는 것**으로 판정한다.

## 11. 구현 순서

1. **R0 — Corpus와 native baseline**
   - 기존 native detector 결과를 기준으로 6/16 mm와 환경별 test corpus를 고정한다.
   - model manifest, data provenance, model card 형식을 먼저 만든다.
2. **R1 — PF-AssistNet shadow mode**
   - 작은 candidate classifier를 C++ in-process로 연결한다.
   - 결과는 기록만 하고 native candidate를 아직 제거하지 않는다.
3. **R2 — Opt-in candidate ranking**
   - false positive 감소와 solve 성공률 향상이 hold-out 밤에서 확인될 때만 opt-in한다.
4. **R3 — PF-RescueNet shadow mode**
   - 달/광해/solver failure 조건에서 선택 tile만 3-head network로 처리한다.
5. **R4 — Lens-specific rollout**
   - 16 mm와 6 mm 각각의 profile/model fingerprint를 검증한 뒤 단계적으로 기본 활성화한다.
6. **R5 — Full-frame model 연구**
   - Pi 5 CPU 또는 선택 NPU에서 실제 P95가 native + tile 계획보다 이득일 때만 재검토한다.

## 12. 라이선스 및 재사용 판단

이 절은 법률 자문이 아니라 배포 전 검토 항목이다.

| 대상 | 판단 |
|---|---|
| Zhao 연구의 GitHub code/weights/data | 공개 저장소이지만 LICENSE가 확인되지 않는다. 직접 복사·수정·배포하지 않는다. 방법은 clean-room 설계 참고로만 사용 |
| Huang, ATD-DL, 각종 논문 | 논문 접근 권한과 implementation/weight 재사용 권한은 다르다. 명시적 code/model license가 없으면 재사용하지 않는다 |
| AutoSourceID-Light source | Apache-2.0으로 상업 사용 가능. 단 pretrained weight와 Zenodo training data의 권리는 별도로 확인한다 |
| SpaceDevEngineer TESS Star Tracker source | MIT. 단 data, catalog, third-party dependency의 권리와 실시간성은 별도 검토한다 |
| Hipparcos/Tycho catalog | ESA가 CC BY-NC 3.0 IGO로 안내한다. 상업 제품의 학습 데이터·제품 번들·weight provenance에 무심코 사용하지 않는다 |
| 자체 C++/자체 model | 현 PiFinder 저장소가 GPLv3이므로 동일 GPLv3이 가장 단순하다. 독립 배포 라이브러리로 분리한다면 저작권자·결합 방식·third-party notice를 검토해 별도 라이선스를 결정한다 |

상업 배포물에는 source SBOM뿐 아니라 다음을 포함한다.

- THIRD_PARTY_NOTICES
- MODEL-LICENSE
- model SHA-256와 model card
- training data provenance 및 제외한 비상업 data 목록
- backend별 런타임과 optional accelerator 의존성

## 13. 참고 자료

1. Zhao et al., [Real-Time Convolutional Neural Network-Based Star Detection and Centroiding Method for CubeSat Star Tracker](https://arxiv.org/html/2404.19108v2)
2. Zhao 연구 공개 저장소 — [CNNStarDetectCentroid](https://github.com/HongruiZhao/CNNStarDetectCentroid)
   명시적 LICENSE 부재의 의미 — [GitHub licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
3. Huang et al., [Physics-based simulation and multi-task learning for end-to-end star point extraction](https://doi.org/10.1364/OPTCON.591688)
4. He et al., [ATD-DL: a deep learning framework for faint astronomical target detection](https://www.frontiersin.org/journals/astronomy-and-space-sciences/articles/10.3389/fspas.2026.1782465/full)
5. Stoppa et al., [AutoSourceID-Light](https://github.com/FiorenSt/AutoSourceID-Light)
6. [SpaceDevEngineer TESS Star Tracker](https://github.com/SpaceDevEngineer/star-tracker)
7. [ncnn license](https://github.com/Tencent/ncnn/blob/master/LICENSE.txt), [ONNX Runtime license](https://github.com/microsoft/onnxruntime/blob/main/LICENSE), [TensorFlow license](https://github.com/tensorflow/tensorflow/blob/master/LICENSE)
8. ESA, [Hipparcos and Tycho catalogues license](https://www.cosmos.esa.int/web/hipparcos/catalogues)
