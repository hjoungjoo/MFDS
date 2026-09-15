# Cedar 관련 소스·라이선스 배포 점검

후속: 테스트 기본 검출을 별도 native worker+memfd로 전환했다.
[구현 프로토콜](../PROCESS_PROTOCOL.md)을 참고한다. 아래 표는 명시된 점검 커밋의
기록이며, 프로세스 분리만으로 결합 배포의 법적 적합성을 확정하지 않는다.

점검일: 2026-09-15. 대상은 MF_PiFinder `24bf58cd`, mf_detect_star `b0ce2f3`,
운영 checkout과 설치·갱신 경로다. 라이선스 본문, 추적 파일, upstream 비교,
native 이력, 동적 라이브러리 연결, systemd 실행 경로를 확인했다.
이 문서는 소스/조건 검토이며 권리 귀속이나 별도 계약의 법률적 확정은 아니다.

## 결론

**테스트 HEAD의 일반 실행 경로에서는 Cedar Detect가 제거됐다. 그러나 현 상태를
그대로 상용 배포해도 문제가 없다고 확정할 수는 없다.** 핵심은 MF FSL의 GPL
결합 배포 권한과 운영 이미지/설치·갱신 경로다. 소스 제공만으로 둘이 해결되지는 않는다.

MF 자체의 권리를 보유한 당사자는 자기 코드의 상용 제공을 허락할 수 있다.
따라서 "MF에 FSL을 붙였으니 제작자 자신도 판매할 수 없다"는 판단은 잘못이다.
다만 다른 저작권자의 PiFinder GPL 조건까지 면제할 권한이 생기는 것은 아니다.

## 확인한 항목

| 항목 | 확인 결과 | 배포 판단 |
|---|---|---|
| 테스트 HEAD의 Cedar Detect 실행 파일 | `bin` 추적 파일은 과거 고지와 README뿐 | 제거 확인 |
| 테스트 HEAD의 Cedar client/proto/pb2 | vendored solver 목록에서 제외 | 제거 확인 |
| 정상 검출 경로 | GPL `star_detect.py` → `ctypes.CDLL` → MF `.so` | FSL/GPL 결합 조건 정리 필요 |
| Cedar 비교 스크립트 | 외부 proto 경로와 실행 중 서버를 명시적으로 받아 쓰는 선택 도구 | 테스트 사용과 판매 제품 포함을 구별 |
| Cedar Solve/Tetra3 | 고정 upstream의 Apache-2.0 및 원래 Tetra 고지 유지 | Cedar Detect의 FSL과 별개 |
| 운영 장비 | Cedar 서비스가 운영 `PiFinder/bin/cedar-detect-server-aarch64` 실행 | 판매 이미지로 그대로 복제하면 Cedar 포함 |
| 신규 설치 | `pifinder_setup.sh:50`이 `main` recursive clone | 테스트 HEAD 유지 보장 없음 |
| 기존 갱신 | `pifinder_update.sh:8`이 `release` checkout, `sys_utils.py`에서 호출 | 테스트 HEAD 유지 보장 없음 |
| 오래된 설치 백업 | 추적 중인 `.bak`이 upstream release clone 및 Cedar enable | 판매 배포 대상에서 분리 필요 |
| `cedar_*` 변수/과거 문서/고지 | 호환 이름·설계 이력·출처 표시 | 이름만으로 FSL 코드가 되는 것은 아님 |

## 1. FSL native와 GPL PiFinder 직접 연결 — 미해결

PiFinder 루트와 `integrations/pifinder/`는 GPLv3이다. 현재 MF native 표기는
`LicenseRef-Cedar-FSL-1.1-MIT-5year`이며 competing use에 제한을 둔다.
`integrations/pifinder/PiFinder/star_detect.py:40`의 `ctypes.CDLL`은 동일 프로세스의
직접 라이브러리 연결이다. 저장소나 디렉터리를 분리했다고 독립 프로그램으로
판정할 수 없다.

GPLv3 §5/§10 및 FSF의 비호환 라이브러리 해설에 비추어, **FSL만을 근거로 한
결합물 배포는 GPL 호환 문제가 있다.** 별도 예외/호환 라이선스의 명확한 근거가
필요하다. 기존 제3자 GPL 코드에 대한 예외를 우리가 임의로 추가할 수는 없다.
이는 확인된 코드 구조에 근거한 배포 위험 판단이며 법원의 개별 판단을 대신하지 않는다.
[GPLv3](https://www.gnu.org/licenses/gpl),
[FSF 라이브러리 연결 해설](https://www.gnu.org/licenses/gpl-faq.en.html#GPLIncompatibleLibs).

다만 유효한 과거 MIT 경로가 확인돼 해결 수단이 있다. 아래 두 방법 중 실제로
사용할 배포 근거를 명시해야 한다.

1. 권한 있는 저작권자들이 MF에 GPLv3 호환 선택권을 추가한다. FSL과 GPLv3의
   이중 라이선스를 선택하면 PiFinder 결합 배포는 GPL 경로를 따른다. 이때 GPL로
   받은 사람의 상업적 재배포까지 FSL로 제한할 수는 없다.
2. 이미 MIT로 제공된 native 버전을 근거로 사용·배포하고 해당 고지와 출처를
   보존한다. PiFinder 통합 코드는 기존 GPL 조건을 계속 따른다.

현재 라이선스는 요청대로 유지했으며 이 감사에서 어느 경로도 임의로 선택하지 않았다.

## 2. 과거 MIT 버전과 현재 native 코드 — 기능 차이 없음

과거 MIT 커밋은 `4763a01c1b23c5a0a60ddbfd208f5d18df89c2f6`다.
이 버전과 점검 HEAD 사이의 `src/`, `include/`, native `tests/` 8개 파일은 첫 줄
SPDX 변경을 제외하고 동일하다. Makefile 차이는 라이선스 고지 복사 작업이다.
즉 현재 다단계 검출 기능은 이미 MIT 버전에 존재한다. 최근 속도 개선은 별도의
Apache/GPL 쪽 Tetra3 검색 변경이다. MIT 경로를 택하기 위해 이 개선을 버릴
기술적 이유는 확인되지 않았다.

기존 MIT 고지는 `LICENSES/MIT-legacy.txt`에 남아 있다. 과거에 부여한 MIT 권한은
새 FSL 표기로 소급 취소되지 않는다. 따라서 동일 코드의 기존 MIT 사용까지
새 상용 제한으로 차단할 수 있다고 설명해서도 안 된다.

native 이력과 파일에서 Cedar Detect 구현을 가져온 흔적은 발견하지 못했다.
그러나 Git 작성자와 `PiFinder contributors` 표기만으로 모든 권리 귀속을 증명한
것은 아니다. 실제 권리자·외부 기여 약정은 상용 라이선스 결정 전에 확인할 대상이다.

## 3. Cedar Detect가 남는 운영·배포 경로 — 미해결

운영 PiFinder PID715와 Cedar PID708은 그대로 실행 중이며 drop-in은 없다.
`/home/pifinder/PiFinder` 운영 `main`은 변경하지 않았다. 로컬 `origin/main`에도
Cedar의 aarch64/arm64 실행 파일과 서비스가 추적된다. `release`의 현재 원격
내용은 이번 감사에서 확인하지 않았으므로 포함 여부를 단정하지 않는다.
다만 updater가 검토한 테스트 HEAD를 벗어나는 것은 소스로 확인했다.

따라서 지금 장비의 SD 이미지를 그대로 판매 이미지로 복제하거나 기존 설치·갱신
스크립트를 그대로 사용하면 "Cedar Detect 제외 제품"이라고 보장할 수 없다.
판매용 설치/갱신 대상을 검토한 커밋으로 고정하고 별도의 최종 이미지에서 실행
파일·서비스·의존성을 다시 검사해야 한다. Git 이력에는 삭제 이전 바이너리도
있으므로 전체 작업 디렉터리/이력 번들을 배포할 때는 포함 파일 범위를 따로 확인한다.
단순한 로컬 보관이나 비상업적 소스 이력 공개 자체를 위반이라고 판단한 것은 아니다.

보관된 Cedar 고지 SHA256은
`833715da66aa467c2fbfaa2baf743511c06abb5aa5e0a6905374ceeb4f106dff`로 기존
고정 원문 기록과 일치한다. upstream 현재 공개 원문도 competing use 제한과
버전 공개 후 **5년** MIT 전환을 명시한다. 표준 FSL의 2년으로 해석하면 안 된다.
소스를 함께 주거나 RPC로 별도 실행하는 것만으로 이 제한이 사라지지 않는다.
Cedar를 제품에 남긴다면 실제 용도에 맞는 별도 허락/계약 확인이 필요하다.
[Cedar Detect 원문](https://github.com/smroid/cedar-detect/blob/main/LICENSE.md).

## 4. Cedar Solve/Tetra3 — Apache 고지 보완 완료

upstream `38c3f48f57d1005e9b65cbb26136f9f13ec0a1b0`과 로컬 Git 객체를
대조했다. 포함된9개 upstream 파일 중8개(라이선스/DB 포함)는 그대로이며
`tetra3.py`만 최근 검색 최적화로 달랐다. upstream에는 별도 NOTICE 파일이 없고,
파일 안에 Steven Rosenthal, ESA, 원래 Tetra의 저작권·라이선스 고지가 남아 있다.

Apache-2.0 §4(b)의 수정 사실 고지를 분명히 하기 위해 `tetra3.py` 상단과
`VENDORED.md`에 수정 일자·기반 커밋·변경 내용을 추가했다. 기존 고지는 보존했다.
실행 AST는 모듈 문서를 제외하면 수정 전과 동일한지 검사했다.
`bin/README.md`의 과거 SEP 기본 설명도 현재 MF 우선 정책으로 정정했다.
[Apache-2.0 §4](https://www.apache.org/licenses/LICENSE-2.0),
[Apache/GPLv3 호환 안내](https://www.apache.org/licenses/GPL-compatibility).

이 solver는 Cedar Detect가 아니므로 이름/저작권 고지를 없애거나 FSL로 바꿀
필요가 없다. 반대로 필요한 기존 고지를 제거하면 조건 위반이 될 수 있다.

## 5. 소스 제공 및 범위

GPL 제품 배포는 대응 소스, 라이선스·저작권 고지, 필요한 빌드/설치 자료를 포함해
§6 조건에 맞춰 준비해야 한다. 사용자 제품에 해당하고 설치 권한을 보유하는
상황이면 Installation Information도 검토 대상이다. "소스 링크 하나"만으로
모든 조건이 충족된다고 보지 않는다. [GPLv3 §6](https://www.gnu.org/licenses/gpl).

설치 메타데이터상 SEP1.4.1은 LGPLv3+, grpcio1.64.1은 Apache-2.0,
protobuf4.25.2는 BSD-3-Clause이다. 일반 gRPC/protobuf 패키지가 남았다는
사실을 Cedar FSL 구현 잔존으로 오해하지 않는다. 반면 Cedar 자체의 proto/생성
코드를 함께 배포하는 경우에는 해당 코드의 출처와 조건을 다시 확인해야 한다.
카탈로그 전체·OS 이미지의 모든 패키지·특허·상표·권리자 계약을 망라한 법률 감사는
이번 Cedar 관련 점검 범위에 포함하지 않았다.

라이선스 선택, 서비스, 설치·갱신 동작은 변경하지 않았다. 보고서와 Apache 고지
보완만 승인된 테스트 브랜치에 기록한다. 운영 환경에 변경은 없다.
