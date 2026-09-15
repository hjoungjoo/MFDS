# Licensing and provenance

MFDS public migration (2026-09-16): repository visibility and name changed;
existing license grants, attribution and per-version future-license dates did
not. Native terms remain source-available FSL with a five-year MIT future grant;
PiFinder-derived integration remains GPL-3.0. See [publication provenance](PUBLICATION.json)
and [commercial use](COMMERCIAL_USE.md). The historical audits below retain
their original dates and limitations; public hosting is not a legal clearance.

See the [2026-09-15 distribution audit](docs/test_cedar_free_20260915/LICENSE_AUDIT_ko.md)
for unresolved GPL/FSL integration and installer/image issues. Preserving the
license texts and directory scopes alone does not establish distribution compliance.
The [GPL/FSL options](docs/test_cedar_free_20260915/GPL_FSL_OPTIONS_ko.md) describe
proposed distribution paths; they do not grant a new license.
The [clarified commercial-use policy](docs/test_cedar_free_20260915/MF_COMMERCIAL_POLICY_ko.md)
records the owner's requested approval requirement for MF in products for sale.
It supersedes the earlier recommendation to offer a GPL alternative, but does
not amend LICENSE. The current FSL's Competing Use restriction and five-year
future MIT grant are not equivalent to an indefinite approval requirement for
all products for sale. Integration and prospective terms remain unresolved.

The test integration now defaults to a standalone native worker with generic
image/centroid IPC. The GPL adapter stays under `integrations/pifinder/`; native
`src/server.cpp` uses the existing native terms. Explicit ctypes comparison is
retained. This technical boundary is not a new license grant, GPL exception or
legal determination; see [the protocol](docs/PROCESS_PROTOCOL.md).
The [preprocessing review](docs/test_cedar_free_20260915/PREPROCESS_LICENSE_REVIEW_ko.md)
distinguishes the current GPL-scoped module from a possible additional grant by
its actual rightsholders. No preprocessing license has been changed by that review.

## Native detector

The current native detector uses the same operative terms as Cedar Detect's
LICENSE.md at commit `2f403b8435259263f2a4fcd43f526918fe546d77`:
[immutable upstream license](https://github.com/smroid/cedar-detect/blob/2f403b8435259263f2a4fcd43f526918fe546d77/LICENSE.md).

Cedar labels this text FSL-1.1-MIT but changes the MIT future grant to the
**fifth anniversary** of publication. We retain that five-year text verbatim
from the `Functional Source License` heading onward. The identifier here is
`LicenseRef-Cedar-FSL-1.1-MIT-5year`, so tooling does not confuse it with standard
FSL-1.1-MIT. The upstream license file's SHA256 is
`833715da66aa467c2fbfaa2baf743511c06abb5aa5e0a6905374ceeb4f106dff`.

The licensor notice identifies the existing MF copyright holders, **PiFinder
contributors**, not Cedar's author. No Cedar detector implementation was imported.
The change is published on 2026-09-15. For this publication, the five-year future
MIT grant takes effect on 2031-09-15; each later version has its own publication date.
The controlling text is [LICENSE](LICENSE).

The terms exclude Competing Use, including offering the Software in a commercial
product or service that substitutes for it or provides substantially similar
functionality. Internal use is a Permitted Purpose. Source availability alone
is not a blanket permission for commercial redistribution.

## Retained licenses

| Path | Terms |
|---|---|
| `src/`, `include/`, native `tests/`, build files, project-authored materials | Current [LICENSE](LICENSE), except explicit notices |
| `integrations/pifinder/` | Existing [GPL-3.0](LICENSES/GPL-3.0.txt) from MF_PiFinder |
| `docs/test_cedar_free_20260915/` | Existing [GPL-3.0](LICENSES/GPL-3.0.txt) for imported PiFinder experiment records |
| Earlier MIT releases and incorporated MIT material | Original [MIT notice](LICENSES/MIT-legacy.txt), retained |
| Optional external libpng, NumPy, SciPy, SEP and Tetra3 | Their respective upstream terms; not relicensed by this change |

Previous MIT grants are not revoked. This change does not impose new restrictions
on copies already received under MIT. The imported integration code's provenance
and pre-move hashes are in [SOURCE.json](integrations/pifinder/SOURCE.json).
Consolidating files does not change PiFinder's GPL or SEP's LGPL, and does not
by itself grant permission for every combined commercial distribution.

## 한국어 요약

native 검출기는 사용자 요청에 따라 Cedar Detect의 **5년 뒤 MIT 전환 조건**을
그대로 적용했다. 표준 FSL의 2년 조건으로 표시하지 않는다. 경쟁 제품·서비스의
상용 제공 제한도 원문에 포함된다. 저작권자는 기존 MF 고지를 유지한다.

PiFinder에서 옮긴 통합 코드와 실험 기록의 GPL은 유지한다. 과거 MIT 배포분의
권한을 소급 취소하지 않는다. 라이선스 원문, 적용 범위, 과거 고지는 이 저장소에서
함께 관리한다. 디렉터리 이동은 외부 코드의 재라이선스를 뜻하지 않는다.
