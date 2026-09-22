# 선택적 Raspberry Pi GPU 전처리

`MF_PREPROCESS_ACCELERATOR=cpu|auto|gpu`로 전처리 실행 방식을 선택한다.
기본값은 `cpu`다. 현재 GPU 구현은 **CFA 위상을 보존하는 Gaussian/DoG
점광원 필터만** OpenGL ES 3.1 compute shader로 실행한다. 배경 median/MAD,
연결 성분과 MF4p 검출은 CPU 구현을 사용하며, 시간 누적은 별도
[`MF_PREPROCESS_REDUCTION` 옵션](CPU_PREPROCESS_ko.md)으로 NEON/NumPy를 선택한다.
GPU 옵션은 실험용이며, GPU를 사용할 수 있다는 사실이 성능 향상을 뜻하지 않는다.

| 값 | 동작 |
|---|---|
| `cpu` | 기존 SciPy 경로. EGL/GLES 라이브러리를 로드하지 않는다. |
| `auto` | GPU 사용을 시도한다. 초기화·실행 실패 시 경고를 한 번 기록하고 해당 인스턴스는 CPU로 복귀한다. 속도에 따른 자동 선택은 아니다. |
| `gpu` | GPU 필수. 초기화·실행 실패 시 `GPUUnavailable` 예외를 발생시켜 비교 실패를 드러낸다. |

지원 대상은 Raspberry Pi의 **V3D renderer + OpenGL ES 3.1**이다.
llvmpipe 같은 CPU 소프트웨어 렌더러와 다른 GPU renderer는 거부한다.
Pi 5에서 검증했으며, Pi 4 및 다른 드라이버 버전의 성능·호환성은 검증하지 않았다.
디스플레이 서버 없이 surfaceless EGL을 사용한다. 실행 사용자에게 DRM render
장치 접근 권한이 필요하다. 샌드박스·컨테이너 안에서는 호스트의 GPU가 보이지
않을 수 있다.

## 빌드와 사용

MFDS 개발 checkout에서 실행한다. CPU 빌드에는 새 의존성이 필요 없다.
GPU 빌드는 C++ 컴파일러와 EGL/GLES 개발 헤더·라이브러리가 필요하다.
Raspberry Pi OS의 해당 개발 패키지는 `libegl-dev`, `libgles-dev`다.

```bash
cd /home/pifinder/MFDS
make -j2
make gpu
```

`build/libmf_preprocess_gpu.so`가 추가된다. 환경 변수는 전처리 인스턴스를
만들기 전에 지정한다. 이미 생성된 인스턴스의 모드는 변경되지 않는다.

```python
from PiFinder.mf_star_only_preprocess import MFStarOnlyAccumulator, MFStarOnlyConfig

accumulator = MFStarOnlyAccumulator(
    MFStarOnlyConfig(accelerator="gpu", parallel_scale_workers=3)
)
try:
    result = accumulator.add(raw_frame, saturation_level=4095, fingerprint="geometry")
    print(accumulator.point_backend.active_backend)
    print(accumulator.point_backend.renderer)
finally:
    accumulator.close()
```

`accelerator=None`이면 `MF_PREPROCESS_ACCELERATOR`를 읽고, 명시적 config 값은
환경 변수보다 우선한다. `MF_PREPROCESS_GPU_LIBRARY`로 라이브러리 경로를
지정할 수도 있다. 기본 경로는 canonical 전처리 모듈 옆 MFDS의 `build/`다.
`preprocess_star_evidence()` 직접 호출도 같은 config/env 옵션을 사용하지만,
매 호출 GPU 초기화 비용을 피하려면 accumulator를 재사용한다.

GPU 컨텍스트 생성·연산·정리는 전용 스레드에서 처리한다. 호출 스레드가
바뀌어도 순차 사용 가능하며, accumulator 자체의 동시 `add()` 호출은 지원하지
않는다. GPU를 한 번 사용한 인스턴스는 fork 뒤에 재사용하지 말고 자식에서
새로 만든다. 초기화 전 인스턴스와 CPU 경로는 fork 이후에도 사용할 수 있다.
종료 시 `close()`를 호출한다. `reset()`은 시간 누적만 초기화하고 GPU를 재사용한다.

전처리 Python 모듈과 GPU C++ 코드는 `integrations/pifinder/`의 GPL 범위다.
FSL 별 검출기를 GPL 프로세스에 추가로 로드하지 않는다. GPU 라이브러리가
존재하면 `tools/package_release.py`가 릴리즈에 포함한다. CPU 전용 패키지도
유효하며 이 경우 `auto`는 CPU로 복귀하고 `gpu`는 오류를 반환한다.
PiFinder 운영 반영에는 변경된 MFDS 패키지 배포와 고정 버전 갱신이 필요하다.
개발 checkout에서 빌드하는 것만으로 운영 패키지가 바뀌지는 않는다.

## 정확도와 재현

SciPy의 Gaussian sigma, truncate=4, reflect 경계와 CFA 위상을 유지한다.
각 Bayer 위상에 독립적으로 세로·가로 필터를 적용하고 원래 센서 격자로 반환한다.
GPU는 float32 합산을 사용하므로 CPU와 비트 단위 동일성을 보장하지 않는다.
특히 이후 float16 양자화와 임계값 비교 근처에서는 작은 차이가 확대될 수 있다.
임계값이나 별 개수 조건을 GPU용으로 완화하지 않았다.

```bash
PYTHONPATH=integrations/pifinder pytest -q \
  integrations/pifinder/tests/test_mf_preprocess_accel.py \
  integrations/pifinder/tests/test_mf_star_only_preprocess.py

# 실제 V3D 접근 가능한 환경. GPU 실패를 skip으로 숨기지 않는다.
MF_TEST_GPU=1 MF_PREPROCESS_ACCELERATOR=gpu \
  PYTHONPATH=integrations/pifinder pytest -q \
  integrations/pifinder/tests/test_mf_preprocess_accel.py \
  integrations/pifinder/tests/test_mf_star_only_preprocess.py

PYTHONPATH=integrations/pifinder python3 \
  integrations/pifinder/scripts/benchmark_preprocess_accel.py \
  /path/to/corpus /path/to/new_result.json --frames 12 --repeats 2
```

벤치마크는 기본적으로 `raw_*.tiff`를 읽고 CPU/GPU 순서를 교대한다.
각 반복 첫 4장은 누적 준비로 시간 집계에서 제외하되 정확도 비교에는 포함한다.
필터 시간은 스레드 전달, 버퍼 업로드·실행·동기화·다운로드를 포함한다.
전체 전처리 시간은 배경과 시간 누적까지 포함하고 별 검출 시간은 별도로 기록한다.
픽셀/evidence 차이, MF4p 후보 수와 일대일 최근접 할당의 최대 좌표 차이,
입력·소스·바이너리 해시를 기록한다. 서로 다른 후보 개수도 별도 기록하므로
좌표 차이만으로 동일 검출이라고 판단하지 않는다. 노출·솔빙·UI·마운트는 제외한다.

실측 결과는 [GPU 전처리 테스트 결과](GPU_PREPROCESS_RESULTS_20260923_ko.md)에 있다.
API 기준은 [OpenGL ES 3.1](https://registry.khronos.org/OpenGL-Refpages/es3.1/html/)과
[SciPy Gaussian filter](https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.gaussian_filter.html)다.
