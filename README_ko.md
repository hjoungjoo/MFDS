# MFDS — MF Detect Star 독립 별 검출기

공식 공개 저장소는 [hjoungjoo/MFDS](https://github.com/hjoungjoo/MFDS)다.
최종 소스·전처리·통합 코드·집계 자료를 관리하며, 실행 파일과 ABI의
`mf_detect_star` 이름은 호환성을 위해 유지한다. 공개 열람은 무제한 상용
배포 허락을 뜻하지 않는다. [상용 사용](COMMERCIAL_USE.md),
[라이선스 범위](LICENSING.md), [공개 이관 기록](docs/PUBLIC_MFDS_ko.md)을 참고한다.

`mf_detect_star`는 PiFinder를 import하지 않는 독립 C++20 별 검출기다.
파일 입력 CLI와 Linux memfd 공유 메모리를 사용하는 별도 worker를 제공한다.
PiFinder 통합·전처리는 GPL을 유지하는 `integrations/pifinder`에서 관리한다.
현재 main 기본은 MF4p(1/4 탐색→후보 주변 1/2 정밀화)이며
[메인 확정 결정](docs/MAIN_FINALIZATION_ko.md)에 실측 근거와 채택 구성을 정리했다.
아래 reference 알고리즘과 파일 입력 예제는 별도 비교에도 사용할 수 있다.

구현 우선순위와 장기 구조, AI 후속 연구는 [docs 문서 인덱스](docs/README.md)에서 관리한다.

## 현재 구현 범위

- PNG(선택적 libpng), 8/16-bit P5 PGM, little-endian RAW16 입력
- 1x 또는 2x2 mean binning
- mesh별 median/MAD 배경·지역 잡음 추정
- 포화 pixel과 주변 halo mask
- 지역 정규화 `Z=(I-B)/sigma`
- 두 PSF scale의 정규화된 zero-sum Gaussian/box 응답과 local maximum 검출
- 원본 작업 평면 patch의 centroid, FWHM, eccentricity 검증
- JSON/CSV 후보 출력과 background/noise/Z/response/mask 진단 PGM
- 광해 gradient, 얇은 구름, 중앙 포화 광원, hot pixel, 2x2 좌표 회귀 합성 테스트

얇은 구름으로 background나 local noise가 높아진 mesh는 진단용
`STAR_THIN_CLOUD_CELL` flag만 붙인다. 해당 mesh를 제외하지 않으므로 지역 SNR이 충분한 밝은
별은 계속 검출한다. 두꺼운 구름처럼 실제 별 정보가 없는 영역에서 별을 복원하거나 생성하지
않는다.

이 버전은 정확도 기준을 만드는 full-frame reference 구현이다. 중앙 우선·주변 tile scheduler,
ARM NEON, row streaming, LensProfile은 실제 16 mm/6 mm RAW corpus로 기준 결과를 만든 다음
추가한다.

## 라이선스와 의존성

native 자체 소스에는 MFDS의 **5년 후 MIT 전환 FSL 정책**을 적용한다.
`LicenseRef-MFDS-FSL-1.1-MIT-5year`로 표기한다. 적용 범위와 과거 MIT 고지는
[LICENSING.md](LICENSING.md)에 있다. 옮겨온 PiFinder 통합 코드는 GPL을 유지한다.
detector core는 C++ 표준 라이브러리만 사용한다. PNG
입력은 상업 사용 가능한 libpng가 설치된 경우 자동으로 활성화된다. libpng가 없어도 PGM과
RAW16으로 빌드할 수 있다.

SEP, OpenCV, AI runtime은 아직 연결하지 않았다. 따라서 첫 정확도 실험은 외부 detector 구현과
라이선스에 의존하지 않는다.

## 빌드와 합성 테스트

PiFinder 저장소 루트에서 다음을 실행한다.

~~~bash
make -C mf_detect_star info
make -C mf_detect_star -j2
make -C mf_detect_star test
~~~

산출물은 `mf_detect_star/build/` 안에만 생긴다.

- `build/mf_detect_star`: 파일 입력 CLI
- `build/mf_detect_star_tests`: 독립 합성 회귀 테스트

## 기존 PNG 시험

~~~bash
mf_detect_star/build/mf_detect_star \
  --bin 1 \
  --sigma 4.5 \
  --diag-prefix /tmp/mfds_orion \
  test_images/orion_bad.png
~~~

표준 출력은 JSON이다. `--csv`를 지정하면 다음 열을 출력한다.

`x,y,flux,response_sigma,peak_sigma,fwhm,eccentricity,psf_sigma,flags`

진단 prefix를 지정하면 다음 파일이 생긴다.

- `_background.pgm`: 보간된 저주파 배경
- `_noise.pgm`: 지역 MAD/RMS 상당 잡음
- `_z.pgm`: 정규화 잔차
- `_response.pgm`: 가장 좋은 PSF scale의 DoG 응답
- `_mask.pgm`: 포화 core와 dilation mask

PGM은 ImageMagick, GIMP, Python/Pillow 등에서 열 수 있다.

## RAW16 시험

RAW16은 header 없는 little-endian uint16 row 배열이다.

~~~bash
mf_detect_star/build/mf_detect_star \
  --width 1920 --height 1080 --stride 1920 --max-value 4095 \
  --bin 2 --mesh 64 --noise-floor 2.0 \
  --diag-prefix /tmp/mfds_raw \
  frame.raw16
~~~

`--mesh`는 원본 입력 좌표 기준이다. `--bin 2 --mesh 64`이면 2x2 작업 평면에서 32 pixel
mesh가 된다. 반환되는 `x,y,FWHM,psf_sigma`는 다시 원본 입력 좌표로 변환된다.

## 초기 parameter 의미

| 옵션 | 의미 | 초기 권고 |
| --- | --- | --- |
| `--bin` | 검출 작업 평면 binning | solver PNG 1, 1920x1080 RAW는 1과 2를 모두 비교 |
| `--mesh` | 배경을 독립 추정하는 원본 pixel 폭 | 16 mm는 48~96, 6 mm는 radial corpus로 결정 |
| `--sigma` | 정규화 zero-sum PSF 응답 threshold | 4.0~5.5 sweep |
| `--noise-floor` | MAD가 0에 가까울 때 최소 ADU noise | RAW sensor dark frame에서 측정 |

`thin_cloud_cells`는 배경 또는 잡음이 frame median보다 높은 cell의 진단 개수일 뿐, 구름의
정확한 분류 결과가 아니다. 이 값만으로 tile을 제거해서는 안 된다.

## 실제 영상 수집 시 필요한 정보

16 mm 또는 6 mm 이미지를 추가할 때 가능하면 다음을 함께 기록한다.

- 원본 RAW/PNG와 bit depth, width/height/stride
- 렌즈, sensor, exposure, gain
- 달·가로등의 대략적인 위치
- 맨눈으로 확인되는 밝은 별의 대략적인 위치 또는 기존 solver 결과
- clear / thin cloud / thick cloud / flare / dew 분류

실제 corpus에서는 “후보가 많다”가 아니라 solver와 일치하는 별의 recall, false candidate 수,
centroid residual, P50/P95 시간을 함께 평가한다.

## 통합 관리와 최신 테스트 기본값

native core, C ABI v1, 전처리·검출 연결 모듈, 비교 도구와 관련 테스트의 정본은
이 저장소다. PiFinder는 고정 커밋 submodule과 상대 symlink로 참조한다.
[통합 사용법](integrations/pifinder/README.md),
[실측 기본값과 비교 안내](docs/test_cedar_free_20260915/FIELD_GUIDE_ko.md)를 따른다.

## Binary distribution

Release assets `MFDS-VERSION-linux-aarch64.tar.gz` and `MFDS-VERSION-linux-x86_64.tar.gz` contain compiled native binaries and the GPL Python integration. Consumers install these packages without cloning or compiling MFDS. Source changes and binary builds are maintained here. See [binary release guide](docs/BINARY_RELEASES_ko.md).
