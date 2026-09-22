# Raspberry Pi 4·5 CPU 누적 최적화

시간 누적의 신호 합산, evidence 합산, 지속성 횟수, 단일 프레임 마스크 OR를
한 번의 NEON 순회로 처리한다. 같은 영상을 여러 번 읽고 쓰는 비용을 줄인다.
GPU 기본값은 계속 꺼져 있으며, DoG는 SciPy CPU 경로를 사용한다.

## 선택과 호환성

`MF_PREPROCESS_REDUCTION`은 DoG의 `MF_PREPROCESS_ACCELERATOR`와 독립적이다.

| 값 | 동작 |
|---|---|
| `auto` (기본) | 지원되는 ARM64 Linux와 라이브러리에서는 NEON. 사용할 수 없으면 NumPy로 자동 복귀한다. |
| `numpy` | 기존 NumPy 누적을 강제한다. 네이티브 누적 라이브러리를 로드하지 않는다. |
| `neon` | 검증용 NEON 강제. 사용할 수 없으면 `ReductionUnavailable` 예외를 발생시킨다. |

라이브러리는 `-march=armv8-a -mtune=generic`으로 빌드한다.
파이 4 Cortex-A72와 파이 5 Cortex-A76의 공통 FP32/NEON 명령을 사용한다.
Linux `HWCAP_ASIMD`를 확인한 뒤 실행하며, 파이 모델 이름으로 CPU 기능을 추측하지 않는다.
파이 5 전용 명령을 요구하지 않는다. A76용 컴파일 설정도 따로 시험했지만
이번 누적 커널에서 개선을 확인하지 못해 배포 경로에 추가하지 않았다.

라이브러리 없음·ABI 불일치·지원하지 않는 CPU·실행 오류는 `auto`에서 인스턴스당
한 번 기록하고 NumPy로 돌아간다. 32비트 프로세스나 비 ARM 장비는 라이브러리를
로드하기 전에 제외한다. 이는 전처리의 호환 경로이며, MFDS 전체 패키지의
32비트 지원을 추가하는 변경은 아니다. 현재 릴리즈 대상은 Linux aarch64/x86_64다.

네이티브 경로는 1~64장의 연속·정렬된 float32 신호/evidence와 bool 마스크를
지원한다. 미리 evidence를 제한할 수 없는 특수 임계값 설정, 더 긴 누적 창,
지원하지 않는 배열 배치는 `auto`에서 기존 NumPy 연산을 유지한다.
`active_backend`와 `fallback_reason`으로 선택 결과와 이유를 확인할 수 있다.

## 빌드와 사용

새 외부 의존성은 없다. `make`, `make all`, `make runtime`은 공통 NEON 라이브러리를
빌드한다. 누적 라이브러리만 빌드하려면 다음 명령을 사용한다.

```bash
make preprocess

# 권장 기본값: CPU DoG + 사용 가능한 NEON 누적
export MF_PREPROCESS_ACCELERATOR=cpu
export MF_PREPROCESS_REDUCTION=auto

# 기존 누적과 비교할 때
export MF_PREPROCESS_REDUCTION=numpy
```

```python
from PiFinder.mf_star_only_preprocess import MFStarOnlyAccumulator, MFStarOnlyConfig

accumulator = MFStarOnlyAccumulator(
    MFStarOnlyConfig(accelerator="cpu", reduction_backend="auto")
)
try:
    result = accumulator.add(raw_frame, saturation_level=4095, fingerprint="geometry")
    print(accumulator.reduction_backend.active_backend)
    print(accumulator.reduction_backend.fallback_reason)
finally:
    accumulator.close()
```

명시적 `reduction_backend`는 환경 변수보다 우선한다. `None`이면 인스턴스 생성 시
환경 변수를 읽는다. 기본 라이브러리는 canonical MFDS의
`build/libmf_temporal_reduce.so`이며, 실험용 경로는
`MF_PREPROCESS_REDUCTION_LIBRARY`로 지정한다.

`tools/package_release.py`는 빌드된 라이브러리를 패키지 및 SHA256 manifest에
포함한다. 라이브러리가 없는 기존/최소 패키지도 NumPy로 동작한다.
변경된 MFDS 패키지를 배포하고 PiFinder의 고정 버전을 갱신해야 운영에 반영된다.
개발 checkout의 수정·빌드는 이미 설치된 PiFinder 패키지를 변경하지 않는다.

## 정확도와 검증

기존 float16 왕복 양자화, 프레임별 가중치, evidence 제한, 합산 순서, 임계값,
형태학 처리를 유지한다. 누적은 FP32이며 fast-math와 FMA 결합을 사용하지 않는다.
프레임 간 합산 순서를 바꾸지 않으므로 이번 실영상 비교는 픽셀과 evidence의
바이트 단위 동일성 및 진단값 동일성을 요구한다.

```bash
make test
MF_TEST_NEON=1 PYTHONPATH=integrations/pifinder pytest -q \
  integrations/pifinder/tests/test_mf_temporal_reduce.py \
  integrations/pifinder/tests/test_mf_star_only_preprocess.py

PYTHONPATH=integrations/pifinder python3 \
  integrations/pifinder/scripts/benchmark_temporal_reduce.py \
  /path/to/corpus /path/to/new_result.json --backend auto --frames 12 --repeats 2
```

벤치마크는 같은 입력에서 실행 순서를 교대하며 전체 전처리와 누적 시간을 각각
기록한다. 매 반복의 첫 4장은 누적 준비이므로 시간 집계에서 제외하되 정확도는
검증한다. 노출·검출·솔빙·UI 시간을 포함하지 않는다. `--backend neon`은
NEON 사용을 필수로 요구하고, `--backend auto`는 실제 선택 경로와 복귀 이유를 기록한다.

## 2026-09-23 적용 후 실측

파이 5, 1920×1080 실영상, CPU DoG, background workers=3, 누적 5장을 사용했다.
영상 묶음별 12장×2회, 실행 순서 교대, 반복마다 첫 4장을 제외한 16회씩의 중앙값이다.
두 묶음 모두 `auto`가 NEON을 선택했고, 준비 프레임을 포함한 총 48쌍의 출력
픽셀·evidence·진단값이 정확히 일치했다.

| 영상 묶음 | 기존 NumPy 전체 전처리 | NEON 전체 전처리 | 시간 감소 |
|---|---:|---:|---:|
| 고정 검증 영상 | 1,395.0 ms | 1,240.3 ms | 11.1% |
| 달·도시 영상 | 1,339.3 ms | 1,252.4 ms | 6.5% |

누적 단계 자체의 중앙값은 각각 131.2→41.3 ms, 131.2→47.1 ms다.
같은 A/B 실행 내 결과이며, 이전 GPU 실험의 별도 실행 시간과 직접 비교하지 않는다.
백그라운드 부하가 있는 로컬 측정이므로 현장 전체 솔빙 속도나 파이 4의 향상을
보장하는 수치는 아니다.

파이 5 컴파일 비교는 동일한 1080p 5장 누적을 순서 무작위로 30회 실행하고 첫
6회를 제외했다. 공통 설정 44.4 ms, `-march=armv8-a -mtune=cortex-a76` 48.6 ms,
`-mcpu=cortex-a76` 48.0 ms였다. 세 출력이 일치했으나 A76 설정의 이득이 없어
공통 설정을 채택했다. 파이 5 전용 명령 전체의 가능성을 배제하는 결과는 아니다.

검증 범위는 다음과 같다.

- 실제 파이 5: Python 누적/전처리 77개, 실제 V3D 옵션 포함 GPU/전처리 32개 통과
  (전처리 20개는 두 실행에 공통).
- 네이티브 detector 7개와 NEON 누적 창·꼬리 픽셀·임계값 검증 35개 통과.
- QEMU Cortex-A72와 Cortex-A76에서 같은 NEON 라이브러리 검증 각각 35개 통과.
  파이 4 실기기 테스트와 속도 측정은 수행하지 않았다.
- NEON 미지원 stub 라이브러리에서 정책/전처리 34개 통과, 실제 NEON 전용 43개는 제외.
  NumPy 강제 시 기존 전처리 20개 통과.
- Ruff, mypy, 라이선스 배치, 바이너리 버전 검증 통과.

원시 측정 자료는 이 장비의 `PiFinder_test_data/results/` 아래
`neon_apply_20260923_validation.json`, `neon_apply_20260923_moon_city.json`이며,
CPU별 컴파일 비교와 호환성/패키지 검증 자료는
`PiFinder_test_data/work/neon_apply_20260923/`에 보관한다.

지원 근거:
[Pi 4 사양](https://www.raspberrypi.com/products/raspberry-pi-4-model-b/specifications/),
[Raspberry Pi 프로세서 문서](https://www.raspberrypi.com/documentation/computers/processors.html),
[Linux ARM64 HWCAP](https://www.kernel.org/doc/html/latest/arch/arm64/elf_hwcaps.html).
