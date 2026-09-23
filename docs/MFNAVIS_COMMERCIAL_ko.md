# MFNavis 판매용 빌드 — 2026-09-23

- 제품 브랜드: **MFNavis**
- 판매·배포: **FNPD 한국** (대한민국 소재 FNPD)
- 제작·수정: **MagicFly**

## 권리와 출처

MagicFly의 자체 작성·수정 부분을 표시하며 기존 PiFinder 코드 전체의
단독 소유나 FNPD로의 권리 양도를 주장하지 않는다. native 자체 작성 부분,
PiFinder GPL integration, legacy MIT의 구분은 `LICENSING.md`가 기준이다.
기존 FSL 본문·5년 기산일·MIT 허락은 변경하지 않는다. 과거 감사 문서는 당시
기록이며 현재 제품명과 판매 프로필은 이 문서를 따른다.

## 빌드

```sh
make -j2 commercial
```

`dist/commercial/MFDS-<version>-linux-<arch>-commercial.tar.gz`와 SHA256이 생성된다.
`PACKAGE.json`의 `profile`은 `commercial-process-only`다. 판매 프로필은
별도 worker 실행 파일만 허용한다. 개발 빌드 디렉터리에 `.so`가 남아 있어도
패키지에 포함하지 않으며 Python native 로더 정의와 import도 제거한다.
검출기 `ctypes` 선택은 ValueError로 거절한다. 전처리 기본값은 CPU/NumPy이고,
GPU/NEON 명시 선택은 unavailable 오류, auto는 CPU/NumPy로 처리한다.
환경변수로 외부 `.so` 경로를 지정해도 로딩 코드가 없다.

이 제외 범위는 MFDS와 MF 전처리의 직접 native linking이다. NumPy, SciPy,
SEP, 카메라 드라이버 및 OS 자체의 정상적인 native 의존성을 없앤다는 뜻은 아니다.
별도 프로세스라는 사실만으로 GPL/FSL 결합 배포의 법적 판단을 확정하지 않는다.

패키지에 변환된 GPL Python 소스를 그대로 동봉한다. 변환 도구는
`tools/commercial.py`이며 원본 주석과 출처는 유지한다. 수정된 작업 트리에서
만든 것은 `source_dirty: true`인 검토 후보이며 정식 판매 이미지로 승인하지 않는다.
기존 v0.4.0 일반 배포 파일 및 해시는 변경하지 않는다. 새 정식 배포에서
상용 패키지의 별도 SHA256과 manifest SHA256을 제품별 lock에 고정해야 한다.
