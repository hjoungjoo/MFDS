# 원본 PiFinder의 Cedar 결합·배포 확인

2026-09-15. 작업 전 범위: 원본의 공개 소스·배포 문서·관련 PR에서 Cedar 사용
허락과 실행 구조를 확인하고 MF와 비교한다. 원작자에게 연락하거나 운영 서비스,
실제 라이선스 또는 Git 이력을 변경하지 않는다.

## 확인한 사실

GitHub API로 확인한 `brickbots/PiFinder`의 `release` 커밋은
`86d9c2a490c8a2c4b5f5b77d271fc2ecb0bf71dc`다. 검색 색인의 오래된 README 대신
이 커밋의 실제 파일을 직접 읽었다.

1. **Cedar Detect의 별도 상용 허락을 명시한다.** README와 `bin/README.md`는
   PiFinder가 공개 FSL이 아닌 Cedar 저작권자 Steven Rosenthal의 별도 허락으로
   Cedar Detect 바이너리를 상용 제품에 포함한다고 설명한다. 다른 상용 포크나
   재배포자에게 이 허락이 자동 확장되지 않는다고도 명시한다.
   [배포 안내](https://github.com/brickbots/PiFinder/blob/86d9c2a490c8a2c4b5f5b77d271fc2ecb0bf71dc/bin/README.md).
2. **별도 실행 서버다.** `pi_config_files/cedar_detect.service`는 독립 바이너리를
   포트 50551로 실행한다. `solver.py`의 `PFCedarDetectClient`는 gRPC로 접속하고,
   개발 환경에서 서버가 없으면 별도 subprocess로 실행할 수 있다.
   [서비스](https://github.com/brickbots/PiFinder/blob/86d9c2a490c8a2c4b5f5b77d271fc2ecb0bf71dc/pi_config_files/cedar_detect.service),
   [호출 코드](https://github.com/brickbots/PiFinder/blob/86d9c2a490c8a2c4b5f5b77d271fc2ecb0bf71dc/python/PiFinder/solver.py).
3. **입력은 이미지, 출력은 검출 좌표다.** 원시 uint8 이미지 바이트는 공유 메모리로
   전달하고 gRPC 요청에 이름·크기·검출 매개변수를 보낸다. 공유 메모리가 실패하면
   메시지 안에 이미지 바이트를 넣는다. Cedar 연결 실패 시 Tetra3 검출로 대체한다.
   공유 메모리 존재 자체보다 실제 데이터와 결합 의미를 판단해야 한다.
4. **PiFinder GPL과 Cedar 라이선스를 구분한다.** 루트 LICENSE는 GPLv3 전문이고
   `bin/LICENSE-cedar-detect.md`가 별도로 있다. Cedar Solve는 Apache-2.0으로
   설명한다. Tetra3/Cedar Solve gitlink는
   `38c3f48f57d1005e9b65cbb26136f9f13ec0a1b0`이다.
   [README](https://github.com/brickbots/PiFinder/blob/86d9c2a490c8a2c4b5f5b77d271fc2ecb0bf71dc/README.md),
   [GPL](https://github.com/brickbots/PiFinder/blob/86d9c2a490c8a2c4b5f5b77d271fc2ecb0bf71dc/LICENSE).

라이선스 설명을 추가한 [PR #448](https://github.com/brickbots/PiFinder/pull/448)은
2026-05-29 병합됐다. 공개 PR 본문 역시 별도 상용 허락을 설명하며, 조회 시점의
issue comments/reviews/review comments는 모두 비어 있었다.

## 확인되지 않은 부분

검토한 release README, bin 안내, LICENSE 파일과 PR에는 **별도 계약 전문이나
GPL 코드 권리자들의 연결 예외 문안**이 없다. 공개 설명으로 허락의 존재는 확인할
수 있지만, 정확한 범위·수령자 권리·GPL 결합에 대한 계약 처리를 확정할 수 없다.
별도 서버라는 사실과, 그 이유가 GPL 대응이라는 추정은 구분한다.
릴리스 설명은 서비스화의 이유를 안정성·자원 관리로 설명한다.
[v2.4.0 릴리스](https://github.com/brickbots/PiFinder/releases/tag/v2.4.0).

별개 프로그램의 묶음 배포는 각 라이선스를 유지할 수 있다. 반면 긴밀히 결합된
하나의 저작물이라면 Cedar 측 상용 허락만으로 제3자 GPL 의무까지 면제되는 것은
아니다. 소켓/프로세스 분리는 판단 요소이며 자동 면책 조건은 아니다.
공개 자료만으로 원본의 위반이나 완전한 적법성을 단정하지 않는다.
[FSF 결합 판단](https://www.gnu.org/licenses/gpl-faq.en.html#MereAggregation),
[연결 예외](https://www.gnu.org/licenses/gpl-faq.en.html#GPLIncompatibleLibs).

## 현재 MF와의 차이 및 적용 방향

| 항목 | 원본 PiFinder + Cedar Detect | 현재 테스트 PiFinder + MF |
|---|---|---|
| 검출기 실행 | 별도 프로세스/서비스 | Python에서 `ctypes.CDLL`로 같은 프로세스에 로드 |
| 입력·출력 | gRPC + 이미지 공유 메모리/바이트, 별 좌표 반환 | native 함수 직접 호출 |
| 검출기 상용 권한 | Cedar 권리자의 별도 허락을 명시 | MF의 실제 권리 범위에서 제품 사용·타사 허락 정책을 정할 수 있음 |
| GPL 처리 | 본체 GPL 유지, 계약 전문/연결 예외는 확인되지 않음 | 본체 GPL 유지, 직접 연결의 결합 배포 문제는 미해결 |

MF에는 **독립 실행 가능한 검출 서버와 일반 이미지/좌표 인터페이스**를 마련하는
방향이 원본과 더 가깝다. GPL 어댑터와 전처리·솔빙은 PiFinder 측에 유지한다.
지속 실행 worker와 단순 이미지 전달을 검토하고 실제 독립성과 성능을 확인한다.
MF를 GPL로 바꾸는 것이 유일한 해결책이라는 뜻은 아니다. 반대로 원본을 따른다는
이유만으로 현재 ctypes 경로나 향후 IPC 경로의 배포 적합성을 확정하지 않는다.

사용자는 버전별 5년 FSL과 과거 MIT 코드의 존재를 받아들일 수 있다고 설명했다.
기존 버전의 MIT 전환일은 후속 릴리스로 연장되지 않으며, Git 이력을 지워도
기존 허락은 취소되지 않는다는 기준을 유지한다. 이력 삭제는 실행하지 않았다.

## 작업 후 기록

원본 공개 파일과 PR을 읽기 전용으로 확인하고 사실·미확인 사항을 문서화했다.
루트 GPL 전문의 SHA256은
`3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986`이며
운영 checkout의 GPL 전문과 일치했다. OS 이미지 자체나 비공개 계약은 검토하지
않았다. 코드 실행 경로는 변경하지 않았고 성능 재측정을 수행한 작업이 아니다.
