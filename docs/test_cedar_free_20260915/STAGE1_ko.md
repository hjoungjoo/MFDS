# 1단계 — 격리와 Cedar 없는 SEP 경로

## 작업 전

운영 main을 복제하고 원격 test/cedar-free-20260915를 생성했다. 작업 계획을 먼저 커밋·푸시했다. 운영 서비스 WorkingDirectory는 /home/pifinder/PiFinder/python이며 변경하지 않았다.

## 변경

테스트 checkout에서 Cedar Detect 바이너리·systemd 템플릿·설치 호출과 gRPC/shared-memory 클라이언트를 제거했다. tetra3는 Apache-2.0 코어와 기존 DB만 vendor했고 Detect proto/생성 코드/클라이언트는 제외했다. 소스 이력과 LICENSE는 보존한다. 기존 솔버의 과거 cedar 이름의 좌표 helper/비활성 분기는 남아 있지만 Detect를 import하거나 실행하지 않는다. 기본 검출은 SEP이며 전처리 후 기존 중앙→전체 좌표 변환·품질/연속성 게이트를 사용한다.

테스트 데이터와 runtime 경로를 운영 데이터와 분리했다. scripts/test_runtime.sh는 명시적 요청 시 /run override만 생성하고 restore로 운영 서비스를 복구한다. 실행하지 않았으며 영구 부팅 설정과 서비스 enable 상태는 유지했다. 재부팅하면 /run override가 사라져 기존 서비스가 실행된다.

## 현재 영상 수집

운영 API에 GET만 사용해 고정 장비 RAW 180장을 180.05초 동안 기록했다. SHA256 180개가 모두 다르고 설정은 전후 동일했다. 경로: /home/pifinder/PiFinder_test_data/corpora/20260915_fixed_lights. 마운트 미연결, 조명·광해 있음. 현재 광학 설정은 manual 10.3889 mm이며 과거 기록의 6 mm와 구분했다. TIFF와 메타데이터는 서로 다른 API 호출이므로 원자적인 프레임 메타데이터라고 주장하지 않는다. 전후 제어값도 함께 보관한다.

## 첫 결과

9월 3일 광해 30장: 원본 SEP는 0/30, 전처리 SEP는 워밍업을 제외한 28/29(96.6%) 품질 솔브, 27/29 연속성 통과. Matches 중앙값 15, RMSE 중앙값 45.38 arcsec. 2도 초과 군집 이탈 0. 이는 절대 위치 정확도나 오솔브 부재의 증명이 아니다. 현재 스냅샷의 k1=-0.05로 재생했으므로 과거 k1=-0.0438924 측정과 RMSE를 직접 비교하지 않는다.

검출+전처리 중앙값 약 2.09초, 솔브 약 13 ms. 동시 운영 부하를 통제한 최종 속도 수치가 아니다. 현재 장면 180장과 구름 120장에 대한 전체 재생 및 후속 native 비교는 진행 중이다. 초기 개발 표본과 나머지 평가 표본을 구분한다.

## 검증

좌표/전처리/프레임 짝/스케줄링/GOTO 관련 테스트 101개 통과. backend 계약과 SEP runner 테스트 18개 통과. C++ 합성 테스트 5/5 통과. Python 전체 lint/format 검사 수행; 전체 unit/smoke 2,274개 통과, 2개 skip(선택된 marker 밖 715개 제외). mypy 결과는 후속 문서에 기록한다. 하드웨어 서비스 전환과 실제 마운트 GOTO는 수행하지 않았다.

## 다음 단계

같은 전처리 출력을 cache해 SEP/native의 솔브율·RMSE·좌표 산포를 비교한다. 비닝으로 후보를 찾은 뒤 원본 작은 영역에서 centroid를 다시 계산하는 정확도 실험을 시행한다. 이후 프로파일링과 픽셀/후보 회귀 검증을 거쳐 속도를 개선한다.
