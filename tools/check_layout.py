"""Check licensing scopes and imported source inventory without network access."""

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
identifier = "LicenseRef-Cedar-FSL-1.1-MIT-5year"
license_text = (root / "LICENSE").read_text()
terms = license_text[license_text.index("# Functional Source License") :]
assert (
    hashlib.sha256(terms.encode()).hexdigest()
    == "8f822494dbb1e4ef5f655245257cc449b81450e59dd122f6f9197e1d7622b8c9"
)
assert "fifth anniversary" in license_text
assert "second anniversary" not in license_text
assert identifier in license_text
assert (root / "LICENSE.md").resolve() == root / "LICENSE"
assert (root / "integrations/pifinder/LICENSE").read_bytes() == (
    root / "LICENSES/GPL-3.0.txt"
).read_bytes()
for folder in ("src", "include", "tests"):
    for path in (root / folder).rglob("*"):
        if path.suffix in {".cpp", ".h", ".hpp"}:
            assert f"SPDX-License-Identifier: {identifier}" in path.read_text(), path
inventory = json.loads((root / "integrations/pifinder/SOURCE.json").read_text())
for item in inventory["files"]:
    assert (root / item["to"]).is_file(), item["to"]
print(
    f"License scopes and {len(inventory['files'])} canonical integration files verified"
)
print("License SHA256:", hashlib.sha256(license_text.encode()).hexdigest())
