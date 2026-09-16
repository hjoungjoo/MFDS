# MFDS licensing and provenance

MFDS applies its own Functional Source License policy to its native detector:
**a five-year MIT future grant**, identified as
`LicenseRef-MFDS-FSL-1.1-MIT-5year`. The controlling terms are in [LICENSE](LICENSE).
This identifier distinguishes the policy from the standard two-year FSL-1.1-MIT.

## Native detector

The licensor notice identifies the existing MF copyright holders, **PiFinder
contributors**. Permission requests for MFDS are directed to its maintainers
and relevant rightsholders; see [commercial use](COMMERCIAL_USE.md).

The policy was published on 2026-09-15. That publication receives its future MIT
grant on 2031-09-15; each covered version has its own publication date. A new
release, repository migration or identifier correction does not extend an
earlier version's deadline or revoke rights previously granted.

The terms exclude Competing Use from the Permitted Purpose grant, including
commercial products or services that substitute for the Software or provide
substantially similar functionality. Internal use is a Permitted Purpose.
Public source availability is not blanket permission for commercial redistribution.
The terms do not impose indefinite prior approval on every paid product.

## License scopes

| Path | Terms |
|---|---|
| `src/`, `include/`, native `tests/`, build files, project-authored materials | MFDS [LICENSE](LICENSE), except explicit notices |
| `integrations/pifinder/` | Existing [GPL-3.0](LICENSES/GPL-3.0.txt) from MF_PiFinder |
| Imported PiFinder experiment records under `docs/` | Existing [GPL-3.0](LICENSES/GPL-3.0.txt) |
| Earlier MIT distributions and incorporated MIT material | Original [MIT notice](LICENSES/MIT-legacy.txt), retained |
| Optional external libpng, NumPy, SciPy, SEP and Tetra3 | Their respective upstream terms |

The GPL adapter communicates with an independent native worker using image/centroid
IPC; see [the protocol](docs/PROCESS_PROTOCOL.md). Explicit ctypes comparison is
retained. This process boundary is not a new license grant or GPL exception.
Moving integration and preprocessing files into this repository does not
relicense them, and permission from MF rightsholders does not waive third-party
obligations.

The original public migration record is [PUBLICATION.json](PUBLICATION.json).
Imported-file provenance and pre-move hashes are in
[SOURCE.json](integrations/pifinder/SOURCE.json). These are historical inventories,
not the authoritative current license identifier. Repository visibility changes
and description corrections do not alter the operative license terms.

## 한국어 요약

MFDS native 소스에는 **MFDS 자체의 5년 후 MIT 전환 FSL 정책**을 적용한다.
현재 식별자는 `LicenseRef-MFDS-FSL-1.1-MIT-5year`이며, 허용 목적을 벗어나는
상용 사용의 허락은 MFDS의 관련 권리자에게 받아야 한다. 표준 FSL의 2년 조건으로
표시하지 않는다. 실제 조건은 이 저장소의 LICENSE가 정한다.

PiFinder에서 유래한 GPL 소스, 외부 의존성의 조건, 과거 MIT 권한과 기존 저작권
고지는 유지한다. 식별자와 설명을 정리해도 조건·권리자·기산일을 변경하지 않는다.
