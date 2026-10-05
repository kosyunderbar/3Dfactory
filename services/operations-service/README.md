# 관제 서비스

> S04~S06 관제 기능 · S07 실제 GUI 연결 완료 · Java 21 / Spring Boot 4.1.1 / Spring JDBC / PostgreSQL 17.11  
> 내부 사건 반영·등록/업무 이력·최신 스냅샷·REST 조회·신선도/알람

관제 서비스는 유효한 보고를 업무 규칙에 맞게 보관하고 조회한다. 공장의 물리 이동·예약/배출 결정은 Python이 맡는다. 자기 operations_db만 사용하고 수집 DB에 접속하지 않는다. 기존 Flyway V1은 유지한다.

## 실행

전체 환경은 [Compose 안내](../../infrastructure/README.md), 독립 Spring 빌드·DB 없는 bootstrap은 [서비스 안내](../README.md)를 따른다. 일반 모드에서만 업무 API를 등록한다. bootstrap은 /livez만 생존을 확인하고 /readyz는 503이며 업무 API는 없다.

```sh
scripts/dev-stack.sh compose up -d --build --wait --no-deps operations-service
scripts/dev-stack.sh logs operations-service
```

기존 DB가 실행 중이어야 한다. 이 명령은 관제 컨테이너만 반영하며 DB/볼륨을 지우지 않는다. 기본 호스트 HTTP 주소는 http://127.0.0.1:8082다.

필수 설정: OPERATIONS_DB_URL, OPERATIONS_DB_USERNAME/PASSWORD, OPERATIONS_MIGRATION_USERNAME/PASSWORD. 주소/포트는 OPERATIONS_HTTP_ADDRESS/PORT로 변경한다. 선택 설정 INGESTION_DIAGNOSTIC_URL은 독립 실행에서 http://127.0.0.1:8081, Compose에서 http://ingestion-service:8081이다. 상대 서비스의 준비 여부를 관제 기동 의존성으로 추가하지 않았다.

## 내부 사건 반영

`POST /internal/v1/events/apply`에 application/json UTF-8로 `{protocolVersion:1,rawEvent,eventSha256,receivedAt}`를 전달한다. rawEvent는 사건 원본 문자열로 LF 제외, SHA-256은 그 UTF-8 원본의 해시다. 전체 요청 최대512KiB, 원본 최대65,535바이트다. [전달 계약](../../contracts/v1/delivery.md)의 APPLICATION_RESULT를 응답한다.

업무+processed_event+event_projection을 같은 트랜잭션에 저장한다. 같은 원본은 DUPLICATE_APPLIED, 이미 기록한 동일 업무 사실의 새 사건은 FACT_ALREADY_RECORDED다. 낮은 순번의 스냅샷은 STALE_SNAPSHOT_RECORDED로 이력에만 보존한다. 영구 업무 모순은 rollback 후 거절 근거를 별도 저장하고 해당 run을 BLOCKED로 둔다. 참조 미확인은 RETRY_LATER이며 성공 기록을 만들지 않는다. 응답은 실제 COMMIT 반환 후 보낸다.

S05 수집 worker가 이 API를 자동 호출한다. 전달 진단도 내부 HTTP로 제공하며 관제는 수집 DB를 직접 조회하지 않는다. 원본을 TCP 수집한 것과 관제 업무가 반영된 것을 혼동하지 않는다.

## REST 조회

[화면 계약](../../contracts/v1/monitoring.md)의 다음 경로를 구현했다. `{runId}`와 `{id}`는 실제 등록된 값으로 바꾼다.

| 경로 | 내용 |
|---|---|
| GET /api/v1/runs | 실행 페이지 |
| GET /api/v1/factory/layout?runId=… | 공장 등록 구성 |
| GET /api/v1/runs/{runId}/snapshot | 전체 관제 묶음 |
| …/equipment/{id}, …/buffers/{id}, …/vehicles/{id} | 셀/Bay/차량 현재 상세 |
| …/bodies/{id}, …/tags/{tagId}/body | 차체/태그 현재 상세 |
| …/events | 기간/셀/차체/차량/사건 종류 이력 |
| …/quality | 고유 검사 수·PASS/FAIL·비율 |
| …/trends | 검사 추이 버킷 |
| …/alarms | 기간·활성·확인 여부·심각도 알람 페이지 |
| GET /api/v1/system/status?runId=… | 관제 처리 상태와 전달 진단 |
| POST /api/v1/alarms/{alarmId}/acknowledge | `{operatorId}` 최초 확인자/시각 저장 |

등록됐지만 스냅샷 관측이 없는 개체는 data=null, 없는 대상은 404다. 물리 배열은 한 스냅샷, 집계·알람·최근 사건은 REPEATABLE READ의 일관된 관제 묶음에서 읽는다. 서버 epoch와 run별 revision으로 묶음을 구별하며 게시 간격은 500ms다. 알람 POST 결과를 물리 상태에 합치지 않고 다음 revision에서 확인 표시를 갱신한다.

기간은 UTC 밀리초 [from,to), 기본 최근5분/최대24시간이다. quality는 fail/inspected 비율(0~1), 분모0이면 null이다. trends는 bucketMs 1000/5000/60000, 최대300개다. 이력 limit 기본50/최대200, 응답 최대512KiB, cursor 최대2KiB/10분/HMAC 서명이며 필터·limit·첫 조회시각·커밋 fence를 유지한다. 서버 재시작 후 이전 cursor는 새 조회로 바꾼다. GET/POST API는 Cache-Control=no-store다.

## 신선도·알람과 현재 제한

3초/10초 경계로 보고 나이를 평가하고, 복원 상태는 RESTORING으로 표시한다. 수집 진단은 연결500ms/전체응답1초/몸체8KiB 제한으로 조회한다. S05에서 수집 진단 제공 경로를 연결했다. 정상 표본은 AVAILABLE이며 제공 실패/수집 미등록 실행은 UNAVAILABLE이다. 미확인 표본으로 dataStatus를 LIVE/FINISHED로 추정하지 않고 UNKNOWN으로 표시한다. runState=FINISHED는 물리 보고 내용이고 종료 확정 판정과 다르다.

EQUIPMENT_DOWN/BUFFER_FULL/SOURCE_STALE/SOURCE_DISCONNECTED/PROCESSING_BLOCKED를 관리한다. 확인은 최초 operatorId/시각만 기록하고, 정상 복구는 유효 보고의 조건 해소로 처리한다. 오래된 스냅샷·진단 실패·확인 요청만으로 슬롯을 풀거나 고장을 해소하지 않는다. QUALITY_WARNING 생성·알람 메모는 P1이다. S06에서 SSE와 최소 Vue 셀/태그 연결을 완료했으며 전체 관제 GUI는 S07이다. UI 색상 기준은 유지한다.

## 꼭 필요한 검증

```sh
# 별도의 임시 PostgreSQL과 실제 HTTP로 S04만 확인; 기존 Compose DB는 사용하지 않음
python3 scripts/verify-databases.py --suite operations
# 이미 기동한 Compose에서 새 UUID run 한 개만 HTTP 반영/REST/DB 확인 후 정리
python3 scripts/verify-operations.py
```

첫 명령의 검증은 총7개(실제 DB/HTTP4·신선도/상태 판정2·기존 bootstrap1)다. 두 번째는 자동 outbox 전달을 대신한 명시적 시험 호출이다. 고정 fixture를 읽지 않고 기존 Python 모델로 생성한 사건을 새 probe UUID에 연결하며, 모든 소유 표에서 기존 행0건을 확인한 뒤에만 실행한다. 기존 행이 있으면 쓰기·정리 없이 종료한다. 성공 시 60건 처리, 작업3/운송6/고유검사1, 태그 HOLD, 알람 확인·복구, 원본/해시 일치와 중복 처리 결과를 확인했다. 자기 run만 정리하고 볼륨을 보존했다.

기본 `scripts/service-maven.sh operations-service --offline --batch-mode --no-transfer-progress verify`에서는 DB 검증을 건너뛰고 판정2·전송 채널1·bootstrap1을 수행한다. 실제 DB는 환경 플래그를 켜는 helper를 사용한다. 테스트 입력 factory-scenario.ndjson은 기존 Python 모델에서 생성한 결정적 자료이며 자체로 Java 처리 증거가 아니다. 모델 계약을 변경할 때만 `python3 scripts/prepare-operations-fixtures.py`로 재생성한다.

[검증 결과](<../../docs/validation/최소 검증 시나리오와 도구.md>) · [작업19/S04-01](<../../docs/work-notes/작업 19. S04-01 내부 사건 수신과 업무 처리 기록.md>) · [작업20/S04-02](<../../docs/work-notes/작업 20. S04-02 차체·태그와 업무 이력 및 최신 상태.md>) · [작업21/S04-03](<../../docs/work-notes/작업 21. S04-03 관제 조회 API와 검사 집계.md>) · [작업22/S04-04](<../../docs/work-notes/작업 22. S04-04 데이터 신선도와 알람 확인·복구.md>)

## S05 자동 전달 연결

수집 outbox worker/진단 제공과 관제의 기존 API/진단 소비를 연결했다. 실제 수집된 run에서는 신선도·미전달량·연결 표본을 근거로 LIVE/CATCHING_UP 등을 판정하며, RUN_FINISHED 반영과 수집 pending=0/종료 순번 뒤 커서가 확인돼야 FINISHED/ARCHIVED다. 제공 실패는 계속 UNKNOWN이다. `verify-operations.py`처럼 관제만 직접 호출한 run은 수집에 등록되지 않아 진단 미확인이 정상이다.

`python3 scripts/verify-delivery.py --with-restarts`로 모델 사건60건의 실제 TCP→자동 HTTP→두 DB/REST와 관제 중단/수집 재기동을 확인했다. 상세 결과는 [최소 검증 기록](<../../docs/validation/최소 검증 시나리오와 도구.md>)에 있다. S05 당시 SSE/실제 Vue 연결은 후속이었으며 S06에서 최소 연결을 완료했다. 상시 생산은 후속이다.

## S06-02 SSE 전체 상태 전달

`GET /api/v1/runs/{runId}/stream`은 REST와 같은 ViewPublisher의 전체 묶음을 `factory-snapshot`으로 전달한다. id는 serverEpoch:revision이며 sourceSeq/snapshotCapturedAt/viewAsOfAt/publishedAt을 그대로 보낸다. 첫머리 retry:2000, heartbeat5초, 게시 간격500ms다. Last-Event-ID는 이력 재생에 사용하지 않고 최신 전체 묶음을 보낸다. 등록 전404, 등록됐지만 관측 전WAITING/sourceSeq=null이다. 잘못된 메서드/경로 인자/쿼리는 오류 봉투로 응답한다. GET에는 쿼리 인자가 없다.

Servlet 비동기 WriteListener를 이용해 읽지 않는 연결이 게시 스레드를 막지 않게 한다. 연결당 전송 중1개+대기 최신1개만 보관하고 대기 중 낡은 묶음은 교체한다. JSON512KiB 상한을 넘으면 배열을 잘라 정상 응답하지 않는다. 연결 최대20개, 초과429 STREAM_LIMIT/Retry-After:2, 쓰기 진행 제한5초와 구독 종료/오류 시 정리다. 애플리케이션의 구독 자원 회수와 OS/프록시의 실제 버퍼 소비 완료는 구별한다. 전체 실제 느린 네트워크/성능 검증은 S08/S09다.

```sh
# 별도 임시 PostgreSQL/실제 Tomcat에서 SSE 경계만 확인
python3 scripts/verify-databases.py --suite stream
```

필요한3개(제한된 전송 채널1·실제 DB/HTTP SSE1·bootstrap 회귀1)가 통과했다. REST/SSE 같은 epoch/revision, WAITING, 실제 MIME/캐시/버퍼 헤더,20개 연결과21번째429, 해제/재연결을 확인했다. Compose/Nginx와 실제 Chrome에서는 Python 보고225건과 SSE313묶음, 소스 중단/재개 및 최종 GOOD/PASS를 확인했다. SSE DTO는 기존 v1 그대로이며 새 의존성/DDL은 없다.

[작업27/S06-02](<../../docs/work-notes/작업 27. S06-02 REST와 SSE 전체 상태 연결.md>) · [검증 결과](<../../docs/validation/최소 검증 시나리오와 도구.md>) · [화면 계약](../../contracts/v1/monitoring.md)


## S07 화면 연결 상태

기존 v1 layout/전체 snapshot/SSE·events/alarms/quality/trends·알람 확인 API를 실제 Vue 지도·상세·이력·품질/알람 화면이 사용한다. Java 코드·DB 구조·Flyway V1은 변경하지 않았다. 현재 상세는 같은 SSE 전체 묶음, 이력은 별도 조회 기준이다. 품질 합계와 추이는 같은 from/to를 함께 조회한다. 알람 확인 후에도 공장 고장이 유지되고 새 복구 보고에서 정상화됨을 확인했다. [Vue 안내](../factory-console/README.md) · [공유 검증](<../../docs/validation/최소 검증 시나리오와 도구.md>).

## S09 완료와 재실행

[실제 측정/P0 완료표](<../../docs/development/S09 측정·완료 기록.md>) · [처음 실행/기존 데이터/복구/시연](<../../docs/development/초기 실행·재실행·복구·시연.md>) · [새 실제 시연 캡처/단계 재생](<../../docs/development/s09-demo/index.html>).

S09-01~04를 완료했습니다. 측정은 별도 네이티브 검증 DB/임의 loopback 포트를 사용하며 개발 Compose DB/볼륨은 유지했습니다. 정상25.63~25.72건/s·작은 화면 반영 p95 약98ms, 높은 입력 목표 미생성·업무 전달 지연을 구분합니다. SQL 병목이 확인되지 않아 새 index/DDL/의존성은 추가하지 않았습니다. 수집 Flyway1/2·관제1 그대로이며 같은 기존 data 재시작의 선택8개 표 지문이 일치했습니다. 일반 기동은 자동 생산하지 않습니다.

Java 계측은 `-Dfactory.measurement.file=<전용 CSV 경로>`에서만 켭니다. 기본은 비활성입니다. 단일 프로세스 monotonic 구간과 호스트 wall clock을 기록하며 행 상한2,000,000, 오류 시 계측 중단/업무 계속을 적용합니다. CSV를 운영 지표나 새로운 API 계약으로 사용하지 않습니다.
