# MFDS 버전과 릴리즈 관리

`VERSION`의 `MAJOR.MINOR.PATCH`가 기준이다. PiFinder 버전과 독립적으로 관리한다. 호환되지 않는 변경은 major, 호환되는 기능 추가는 minor, 수정은 patch를 올린다. 0.x에서도 기존 IPC/ABI를 바꾸면 별도로 명시한다. 릴리즈 버전, C ABI 번호, `MFDS1` 프로토콜 번호는 서로 다르다.

## 새 릴리즈 절차

1. `VERSION`, `CHANGELOG.md`, `release_notes/vX.Y.Z.md`를 함께 갱신한다.
2. `make -j2 && make test`와 `python3 tools/version.py --check-build build --tag vX.Y.Z`를 통과시킨다. native CI의 sanitizer와 libpng 없는 빌드도 확인한다.
3. 검증 커밋을 main에 푸시하고 해당 커밋에 annotated tag `vX.Y.Z`를 붙여 푸시한다. 태그를 이동하거나 재사용하지 않는다.
4. GitHub 정식 릴리즈를 만든다: `gh release create vX.Y.Z --verify-tag --title "MFDS vX.Y.Z" --notes-file release_notes/vX.Y.Z.md --latest`.
5. PiFinder의 submodule을 그 태그의 정확한 커밋으로 갱신하고 PiFinder를 별도 릴리즈한다. 다른 검출기 변경 없이 PiFinder만 수정할 때 MFDS 버전을 다시 올릴 필요는 없다.

Make는 VERSION에서 헤더를 생성한다. VERSION이 바뀌면 CLI·서버·공유 라이브러리가 다시 빌드된다. 소스 아카이브도 Git 정보 없이 같은 버전을 빌드한다. `mf_detect_star --version`, `mf_detect_star_server --version`, C 함수 `mfds_version()`으로 확인한다. `tools/version.py`는 태그·릴리즈 노트·빌드 결과의 일치를 검사하며 CI가 이를 실행한다.

공개 소스와 릴리즈 노트에만 관측 집계 결과를 포함하고 원본 영상·개인 설정은 포함하지 않는다. GitHub 게시 시각과 태그로 각 릴리즈를 식별한다. `PUBLICATION.json`은 최초 공개 이관의 기록이므로 덮어쓰지 않는다. 새 릴리즈가 과거 공개된 소스의 라이선스 기산일을 소급 변경하지 않으며 라이선스 원문과 경로별 고지를 유지한다.

## 2026-09-16 작업 계획

MFDS v0.2.0에서 버전 표시와 검사 체계를 추가하고 기존 검증된 솔빙 변경을 릴리즈한다. PiFinder m2.6.5는 이 MFDS 커밋을 고정하고 캡처 출처에 MFDS 소스 버전을 추가한다. 기존 m2.6.4 태그·NixOS·서비스 부팅 설정·90초각 사용자 설정을 유지한다.
