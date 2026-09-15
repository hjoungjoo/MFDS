# MF 내부 전처리 추가의 라이선스 검토

2026-09-15. 작업 전 범위: 현재 전처리의 출처·의존성·라이선스 표기를 확인하고,
MF 독립 프로세스에 넣을 때의 조건을 판단한다. 전처리 이식이나 재라이선스는
이번 검토 요청에 포함하지 않는다. LICENSE와 실행 코드는 변경하지 않는다.

## 결론

**전처리 기능을 MF에 추가하는 것 자체가 금지되는 것은 아니다.** MF의 독자
코드로 적법하게 작성하거나, 실제 권리자가 그 전처리에 FSL 사용 허락을 부여하면
MF 전처리+검출을 같은 독립 프로그램으로 구성할 수 있다. 다만 현재 GPL 범위의
파일을 허락 근거 없이 FSL 프로그램에 복사/이식하면 문제가 다시 생긴다.

현재 핵심 전처리는 원본 PiFinder에서 가져온 파일이라고 단정할 수 없다.
아래 이력은 사용자 포크에서 독자적으로 추가한 모듈일 가능성을 뒷받침하므로,
**무조건 전면 재작성보다 먼저 이 파일의 실제 권리와 차용 여부를 확인하는 경로**를
권장한다. Git 작성자 한 명이라는 사실은 모든 저작권·계약 권한의 증명은 아니다.

## 소스에서 확인한 사실

- 대상: `integrations/pifinder/PiFinder/mf_star_only_preprocess.py`.
  현재 [LICENSING.md](../../LICENSING.md)와 [SOURCE.json](../../integrations/pifinder/SOURCE.json)은
  이 파일을 포함한 PiFinder 통합 디렉터리의 기존 GPL을 유지한다고 명시한다.
- 최초 추가는 MF_PiFinder `35ba63eea7a0d29dd41cb669083c4231f8c55294`,
  2026-08-26, Git author `hjoungjoo`, 새 파일 394줄이다.
  [최초 파일](https://github.com/hjoungjoo/MF_PiFinder/blob/35ba63eea7a0d29dd41cb669083c4231f8c55294/python/PiFinder/mf_star_only_preprocess.py).
- 이관 전 `bb57c149`까지 해당 경로의 변경 7개는 모두 author가 `hjoungjoo`다.
  마지막 계산 변경은 `3809fa37`이며, native 저장소의 `b75c5da`에서 이관했다.
- 원본 `brickbots/PiFinder` release 스냅샷
  `86d9c2a490c8a2c4b5f5b77d271fc2ecb0bf71dc`의 recursive tree에는 같은 파일이 없다.
  이는 그 시점의 경로 비교이며 다른 이름으로 된 차용 코드가 전혀 없다는 증명은 아니다.
- 현재 SHA256은
  `666749f6bde11b5ece0bb1ee57c4ff9f0de8ea770e9394b6e321f240749a9c41`로
  이관 기록의 원본 해시와 같다.
- 초기/현재 파일의 AST import를 확인했다. 현재 의존성은 Python 표준 라이브러리,
  NumPy, `scipy.ndimage`다. **PiFinder, Cedar, SEP를 직접 import하지 않는다.**
  주요 처리는 다중 배경 추정, Gaussian 차분, 포화 마스크, 연결 성분 검사,
  시간축 evidence 누적이다. 주변 `sep_detect.py`와는 별개다.

## 선택에 따른 판단

| 선택 | 판단 |
|---|---|
| 직접 소유한 새 전처리를 MF native에 추가 | 제3자 코드·의존성 조건을 지키고 기존 MF FSL로 제공 가능 |
| 현재 핵심 전처리의 모든 필요한 권리를 보유해 FSL로 별도 제공 | 가능. 파일별 근거·새 허락·적용 버전을 명시하고 기존 GPL 사본 권리는 보존 |
| 제3자 GPL 코드가 포함된 파일을 그대로 복사하거나 C++로 번역 | 별도 허락 없이 FSL 전용 결합물로 배포하지 않음. 언어 변경은 권리를 새로 만들지 않음 |
| GPL 전처리를 PiFinder 프로세스에 유지 | 현재 경로 유지. 처리된 이미지를 MF 서버에 전달하며 실제 프로그램 독립성은 계속 검토 |
| SEP 기반 전처리를 MF 안에 추가 | LGPL 및 파일별 조건 검토가 추가됨. 단순히 SEP가 LGPL이라는 이유로 MF 전체가 반드시 GPL이라는 뜻은 아님 |

자기 코드의 권리자는 GPL로 공개한 코드도 다른 비독점 라이선스로 제공할 수 있다.
반면 제3자 GPL 부분의 허락은 해당 권리자에게 필요하다. 기존에 적법하게 받은
GPL 사본의 사용·수정·재배포 권리를 새 FSL로 소급 회수하지 않는다.
MF의 새 변경이 자동으로 과거 GPL에 포함되는 것도 아니다. 명확한 버전·허락
경계가 필요하다. [FSF 자기 코드의 복수 배포](https://www.gnu.org/licenses/gpl-faq.en.html#ReleaseUnderGPLAndNF),
[허락 권한](https://www.gnu.org/licenses/gpl-faq.en.html#GPLIncompatibleLibs).

## 라이브러리와 코드의 라이선스는 별개

검사에 사용한 Python 환경은 NumPy 1.26.4, SciPy 1.17.1, SEP 1.4.1이다.
NumPy/SciPy의 주 라이선스는 BSD 계열이며 상용 사용을 허용한다. 사용한다고
MF 전처리 소스를 GPL로 공개해야 하는 것은 아니다. 소스/바이너리 배포 시
고지·면책 문구와 실제 wheel에 포함된 제3자 라이선스는 보존한다. 주 라이선스만
보고 모든 번들 파일이 같은 조건이라고 판단하지 않는다.
[NumPy](https://numpy.org/doc/2.1/license.html), [SciPy](https://scipy.org/faq/).

설치 SEP의 메타데이터는 LGPLv3+다. upstream은 Source Extractor 유래 코드는
LGPLv3, 일부 파일은 BSD, Python wrapper는 MIT라고 설명한다. wrapper의 MIT만
보고 SEP C core까지 자유롭게 FSL로 바꿀 수는 없다. MF 내부에서 LGPL 라이브러리를
이용한다면 라이브러리 고지·소스 제공, 수정 라이브러리로 교체/재링크할 수 있는
방식과 해당 디버깅을 위한 역공학 허용 등 실제 배포 조건을 맞춰야 한다.
**현재 핵심 전처리에는 SEP 의존성이 없으므로 이를 새로 끌어올 이유는 없다.**
[SEP 파일별 라이선스](https://github.com/sep-developers/sep#license),
[LGPLv3 §4](https://www.gnu.org/licenses/lgpl-3.0.en.html#section4).

## MF에 추가할 때의 권장 경계

권리 확인된 전처리 계산 부분만 MF native에 넣고, PiFinder의 스케줄·정렬·GOTO·
좌표 채택·GPL 어댑터는 PiFinder에 둔다. 단순 이미지/검출 결과 인터페이스를
유지한다. 전처리를 옮기면서 GPL 모듈을 MF 서버 안으로 import하면 현재 분리의
의미가 약해진다. 권리 확인 전에 기존 GPL 표기를 제거하지 않는다.

현재 함수들을 소유자 허락으로 재사용할 수 있다면 라이선스 때문에 반드시
다시 작성할 필요는 없다. C++ 이식 여부는 그다음 성능·정확도 선택이다.
일반 처리 방법을 독립적으로 구현하는 것과 타인의 구체적인 코드를 번역하는
것도 구분한다. 본 검토는 제3자 차용 전수 조사나 권리 귀속의 법적 확정은 아니다.

## 작업 후 기록

현재 표기, 파일 이력, 초기/현재 import, 이관 해시, 원본 release 파일 목록,
설치 의존성 메타데이터와 공식 라이선스 자료를 대조했다. 코드나 라이선스는
바꾸지 않았다. 문서·기존 범위 검사를 적용하며 계산 코드가 같으므로 성능
테스트를 다시 수행한 작업으로 표시하지 않는다.
