# 확정한 테스트 기본값과 실측 비교 절차

## 기본값

누적 실측을 종합한 최신 선택·메모리 범위·비교 옵션은
[현재 테스트 기본값](CURRENT_DEFAULTS_ko.md)을 기준으로 한다.

이 문서와 검출기·전처리·비교 도구의 정본은 `mf_detect_star` 저장소다.
PiFinder의 호환 경로는 고정 커밋 submodule의 파일을 참조한다.
최초 사용 시 PiFinder 루트에서 `bash scripts/setup_mf_detect_star.sh`로 초기화·빌드한다.
라이선스 적용 범위는 [LICENSING.md](../../LICENSING.md)를 참조한다.

현재까지의 고정 장비·광해·구름 자료에서는 **MF4p + auto**를 기본으로 한다.
운영 서비스에 배포했다는 뜻은 아니다. 테스트 소스와 명시적 전환 스크립트의
기본값을 확정한 것이다.

검출 실행 기본은 `MF_DETECT_TRANSPORT=process`다. 독립 native worker와 memfd
이미지 공유 메모리를 호출 스레드별로 재사용한다. 아래 검출·전처리 정책은 같다.
`MF_DETECT_TRANSPORT=ctypes`로 이전 직접 호출과 비교할 수 있다.
[프로토콜·timeout·종료](../PROCESS_PROTOCOL.md), [전환 전 계획](PROCESS_PLAN_ko.md).
[실측 결과와 검증 범위](PROCESS_RESULTS_ko.md)를 함께 참고한다.

전처리의 단일 프레임 별 후보 마스크는 시간 창에 들어올 때 한 번 계산해
재사용한다. 수치와 스케줄 정책은 유지하고 프레임당 중복 분류만 줄인다.
[실행 위치·캐시 비교 계획](PREPROCESS_PLACEMENT_PLAN_ko.md)과
[측정 결과](PREPROCESS_PLACEMENT_RESULTS_ko.md)를 참조한다.
전처리/검출 통합 프로세스는 비교 도구에만 있으며 서비스 기본값이 아니다.

```bash
PYTHONPATH=python python3 python/scripts/compare_detector_transport.py CORPUS CACHE NEW_RESULT.json --frames 120
```

Tetra3 해시 일괄 계산/충돌 조회 최적화도 기본 적용된다.
[속도 개선 검증](SPEED_RESULTS_ko.md)과 [작업 전 계획](SPEED_PLAN_ko.md)을 참조한다.
`TETRA3_SEARCH_OPTIMIZED=0`은 이전 검색으로 비교하고 `1`은 개선 검색을 쓴다.
PiFinder 루트에서 같은 MF 좌표의 A/B는 다음처럼 실행한다.

```bash
PYTHONPATH=python python3 python/mf_detect_star/integrations/pifinder/scripts/compare_search_speed.py CORPUS CACHE NEW_RESULT.json --frames 120
```

- MF 전체 1/4 해상도 탐색 → 후보 주변 1/2 해상도 정밀화.
- response 순서, 최대 48개, 원본 Gaussian 재측정은 끔.
- RAW와 전처리 영상에 같은 검출기를 적용한다.
- 필터 후 MF 후보 5개 미만 또는 native 실행 오류일 때만 SEP 보조 호출.
  MF 후보가 충분하지만 솔빙에 실패하면 기존 전처리 복구 경로를 따른다.
- 전처리 scale worker 3개. RAW 연속 성공 3회부터 비동기로 진행한다.
  RAW 실패·초기 안정화·정렬·보정 때는 같은 프레임 전처리 대기를 유지한다.
- 정상 auto는 RAW + 같은 노출 RAW/전처리 비교로 얻은 bias 보정이다.
  비동기 worker는 전처리/검출을 담당하고 완성 후보 솔빙은 foreground에서 한다.
  **항상 비동기 전처리 좌표를 주 좌표로 사용하는 anchor 방식과 구분한다.**

전처리 anchor + 필터된 RAW 변화량은 고정/느린 이동에는 유망하지만,
이전 합성 진동 구간에서 기존 bias보다 불리했다. 실제 영상의 빠른 진동,
Roll/target pixel/IMU 연계를 검증할 때까지 서비스 기본값으로 승격하지 않는다.
독립 worker가 전처리부터 솔빙까지 하는 실제 실행 비교기는 준비되어 있다.

## 비교 프로필

`python/PiFinder/detector_profiles.py`가 전환과 새 paired 비교기의 공통 정의다.
각 실행은 이전 프로필의 환경변수를 덮어써 순서에 따른 옵션 누출을 방지한다.

| 이름 | 검출 | 용도 |
|---|---|---|
| `mf4p` | 1/4 전체 → 1/2 ROI, SEP 보조 | 기본 |
| `mf2` | 1/2 전체, SEP 보조 | 정확도·속도 기준 |
| `mf1` | 원본 전체, SEP 보조 | 별도 고비용 비교 |
| `mf4p-pure` | MF4p, SEP 꺼짐 | 보조 효과 분리 |
| `mf4o` | 1/4 → 1/2 → 원본 좌표 정밀화 | RAW 실패/보조 증가 확인 |
| `mf8p` | 1/8 → 1/2 ROI | 빠른 탐색의 별 누락 확인 |
| `sep` | 순수 SEP | 비교군; 기본 경로에서는 보조만 |

RAW/전처리를 같은 프레임별로 비교하며 검출기·영상의 실행 순서를 교대로 바꾼다.
`sep_calls`는 모든 SEP 검출, `sep_fallback_calls`는 MF에서 넘어간 보조 호출이다.
검출 성공률과 솔빙 성공률을 구분하고 RMSE는 매칭 별의 각도 잔차(arcsec)로 읽는다.

## 실측 영상 기록

```bash
cd /home/pifinder/PiFinder_test
PYTHONPATH=python python3 python/scripts/capture_detector_corpus.py \
  /home/pifinder/PiFinder_test_data/corpora/field_session_01 \
  --frames 180 --interval 1
```

현재 LiveCam에서 RAW 출력이 활성화되어 있고 original_raw, 비스택이어야 한다.
기록기는 이를 확인만 한다. 카메라 설정이나 서비스를 변경하지 않는다.
2026-09-15 이번 확인에서는 `processing_enabled=false`, RAW 다운로드 HTTP 204,
solution HTTP 503이었다. 새 현장 영상을 수집한 것으로 계산하지 않는다.

테스트 서비스의 새 `/api/observation`은 솔빙 실패 중에도 목표 좌표를 반환한다.
기존 운영 API에는 이 경로가 없으므로 기존 `/api/solution`을 함께 저장하며,
목표는 알 수 없으면 null이다. 구버전 서비스에서 목표를 명시할 필요가 있으면
위 명령에 `--target-ra <J2000 RA도> --target-dec <J2000 Dec도> --target-name <이름>`을
붙인다. 이 값은 `user_declared_target`으로 구분하며 실제 UI 목표를 덮어쓰지 않는다.

## 같은 실측 자료로 일괄 비교

```bash
PYTHONPATH=python python3 python/scripts/field_compare.py \
  /home/pifinder/PiFinder_test_data/corpora/field_session_01 \
  /home/pifinder/PiFinder_test_data/results/field_session_01 \
  --lens manual --manual-focal 10.3889 --frames 180 --timing
```

렌즈 값은 해당 세션의 실제 값으로 지정한다. 기존 캐시가 있으면 `--cache <경로>`를
사용한다. 캐시별 원본 SHA256을 검사하고 불일치하면 중단한다. 출력 폴더는 새로
만들며 덮어쓰지 않는다. `--wide`는 광시야 RAW cloud gate 비교가 필요한 세션에만
사용한다. 같은 조건의 프로필끼리 비교하고 광학계/회전/노출을 섞지 않는다.

산출물:

- `paired.json`: 같은 프레임의 RAW/전처리 성공률, 실제 backend/보조 사유,
  검출·솔빙 시간, RMSE, 매칭 수, 좌표, 관측 스냅샷.
- `summary.json`: 프로필별 집계. `commands.json`, `source_hashes.json`: 재현 명령,
  핵심 Python 및 native 라이브러리 파일 식별.
- `anchor_delay_1.2.json`, `anchor_delay_2.5.json`: 실측 좌표에 **가정한 지연**을
  적용해 RAW, bias, 전처리 유지, RAW 변화량 직접/필터/창 기준 보정을 비교한다.
- `auto_mf4p.json`, `auto_mf2.json`: 실제 전처리·검출·솔빙으로 auto 경로 지연 측정.
- `anchor_pipeline.json`: 독립 전처리/검출/솔빙 worker와 RAW 경로의 실제 병렬 실행.
  RAW가 안정된 anchor가 나올 때까지 사용되고 이후 anchor+RAW 변화량을 비교한다.
  서비스나 마운트에 이 좌표를 발행하지 않는다.

캐시 전처리 시간은 live 지연과 다르다. `--timing`의 실측 harness도 camera IPC,
SQM/UI/마운트 부하를 포함하지 않는다. 짧거나 실패만 있는 자료의 좌표 안정성은
`insufficient_common_frames_after_warmup`으로 보고한다. 실제 GOTO 검증에는
마운트 연결 후 별도 서비스 세션과 입력→발행 지연/도착 오차 기록이 필요하다.

## 서비스에서 프로필을 전환할 때

사용자가 서비스 전환 작업을 요청한 시점에만 아래 명령을 실행한다.

```bash
sudo scripts/test_runtime.sh start                  # mf4p auto
sudo scripts/test_runtime.sh start mf2 auto
sudo scripts/test_runtime.sh start sep auto
sudo scripts/test_runtime.sh start mf4p sync        # 같은 프레임 대기 비교
sudo scripts/test_runtime.sh restore
```

다른 검출기 이름도 위 표와 동일하게 지정한다. 항상 비동기 anchor는 독립 비교기만
제공하며 이 서비스 선택 목록에는 없다. override는 `/run`에만 저장해 재부팅하면
운영 소스로 돌아온다. 이번 작업에서 실제 서비스 전환/재시작은 하지 않았다.

## 저장 좌표의 의미

테스트 소스의 다음 저장 경로에 observation을 추가했다.

- solver/integrator field capture의 각 JSONL: 프레임 메타데이터와 함께 저장.
- 일반 텔레메트리 solve 이벤트: frame_id 및 관측 스냅샷. 목표 ID가 같아도
  좌표/이름이 바뀌면 target 이벤트를 추가한다.
- LiveCam 16-bit TIFF: ImageDescription(tag 270)에 JSON 메타데이터를 내장한다.
  픽셀 값은 유지한다. 스택일 때 input_frame_info는 최신 입력 프레임 정보이며
  모든 누적 노출의 좌표라고 해석하면 안 된다.
- 단일 촬영 저장/텔레메트리 PNG: `.observation.json` 동반 파일.
- 노출 sweep의 per-image metadata, 파이프라인 stage dump metadata.
- HTTP corpus 수집: 전후 observation JSON, TIFF 내장 정보, 파일/픽셀 SHA256.
  TIFF 좌표 시각이 달라 파일 해시가 바뀌어도 동일 픽셀을 새 프레임으로 세지 않는다.

`target`: 선택 천체의 J2000 RA/Dec(도). `target_pixel_yx`는 정렬용 픽셀(Y,X)이다.
`pointing.camera/aligned.solve/estimate`: 카메라 중심/정렬된 관측 방향을 구분한다.
각 좌표는 solve 또는 estimate의 원래 UNIX 시각을 보존한다. snapshot의 UNIX/monotonic
시각은 따로 있다. shared-state 읽기와 RAW 노출은 원자적으로 묶이지 않으므로
snapshot을 해당 노출의 정답 좌표로 간주하지 않는다. 솔빙이 없으면 목표는 남고
pointing은 null 또는 과거 시각의 값으로 기록된다.

`camera_to_selected_target_arcsec`는 카메라 중심과 선택 목표의 각거리다.
접안부 정렬 오프셋, 관측 의도, 시각 차이를 포함하므로 절대 지향 오차가 아니다.
옛 자료에 없는 목표 좌표는 소급 생성하지 않는다. 실제 영상/목표/장비 설정은
로컬에 두고 저장소에는 코드·문서·좌표 없는 집계만 올린다.
