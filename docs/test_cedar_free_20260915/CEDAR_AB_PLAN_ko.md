# Cedar Detect / MF4p 직접 비교 계획

기존 기록은 현재 MF4p와 Cedar의 직접 A/B가 아니므로 동일 실측 RAW와 전처리
캐시를 사용해 검증24장·구름24장을 비교한다. 알고리즘이나 기본값은 변경하지 않는다.

- Cedar: 운영 설정의 12→8-bit shift, sigma=8, max_size=10, binned candidate,
  hot-pixel 검출을 사용한다. 실행 중 서버에 inline gRPC로만 연결하며 공유 메모리,
  카메라 설정, 서비스 생명주기를 건드리지 않는다.
- MF: 기본 MF4p, response/48, 기존 SEP 보조 정책. 실제 backend와 보조 횟수 기록.
- 양쪽 같은 warm/포화 필터, 광시야 RAW cloud gate, 최대48개, 같은 캐시 기하/
  왜곡/Tetra3/품질 gate/중심→전체 cascade를 사용한다. 검출기와 RAW/전처리 순서 교대.
- 원본·캐시 SHA256 검증, 첫 전처리 warmup 제외. 검출 시간은 변환/호출/필터를
  포함하고, Cedar algorithm_time은 별도 기록한다. Cedar inline RPC와 MF ctypes의
  차이가 있으므로 순수 native 코어 속도 비교로 주장하지 않는다.
- 성공률, 매칭 별 수, RMSE, 검출+솔빙 중앙값/p95를 집계한다. 좌표·원본은 로컬.
  이 비교는 동일 조건의 검출기 비교이며 실제 운영 전체 경로/GOTO 평가는 아니다.
