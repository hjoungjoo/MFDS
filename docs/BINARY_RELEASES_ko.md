# MFDS 바이너리 배포

소스 수정은 MFDS 저장소에서만 수행합니다. VERSION·CHANGELOG·릴리즈 노트를 갱신하고 release-assets workflow로 ARM64/x86_64 패키지를 빌드합니다. GitHub Actions 결과를 검증한 후 같은 소스 커밋의 태그와 릴리즈에 tar.gz와 sha256을 게시합니다. PiFinder는 버전·소스 커밋·플랫폼별 SHA-256을 deployment/mfds.lock.json에 고정합니다.

패키지는 native 빌드 산출물과 해석 실행에 필요한 GPL Python 연동 코드·지원 스크립트·회귀 테스트·관련 문서·라이선스 고지를 포함합니다. 소비자에 native src/include/Makefile/.git을 배포하지 않습니다. 소비자 측에서 패키지를 편집하지 말고 MFDS 원본을 수정한 다음 새 버전을 배포하세요.

Bookworm 컨테이너에서 컴파일하므로 glibc 2.36 이상 Linux aarch64/x86_64를 대상으로 합니다. 일반 PiFinder 실행에는 서버를 사용하고 공유 라이브러리·CLI는 회귀와 진단에 사용합니다. 동적 libstdc++ 및 CLI의 libpng 런타임이 필요합니다.

GitHub의 ARM64 runner와 컨테이너 지원: https://docs.github.com/en/actions/reference/runners/github-hosted-runners
