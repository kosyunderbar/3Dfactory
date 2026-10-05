# v1 전달 계약 — 저장 확인·업무 반영·재시도·격리

> 작업 ID: S00-03 · 결정일: 2026-10-05 · protocolVersion: 1  
> 상태: v1 개발 기준 확정. S03 TCP/원본 저장·S04 관제 업무/HTTP·S05 자동 전달/재시작 복구/진단/재개 구현·실제 검증 완료. S06 최소 Python/SSE/실제 Vue 연결도 완료. 전체 관제 GUI도 S07에서 완료했고 전달 protocolVersion=1은 유지.

[사건 계약](events.md)의 schemaVersion=1과 [ADR-001](<../../docs/decisions/ADR-001-서비스 책임과 데이터 소유권.md>)의 서비스 책임을 유지한다. 이 문서는 사건을 전달하고 완료를 확인하는 **두 경계의 약속**이다. 화면용 REST/SSE와 신선도 DTO는 S00-04의 [화면 계약](monitoring.md)을 따른다.

## 1. 완료의 의미

| 경계 | 성공 응답 | 성공 전에 끝낼 저장 |
|---|---|---|
| Python → 수집 | RECEIVED / DUPLICATE_RECEIVED | 수집 DB의 raw_event + event_outbox. 새 실행의 전달 진행 행도 같은 트랜잭션에 생성 |
| 수집 → 관제 | APPLIED / DUPLICATE_APPLIED | 관제 DB의 processed_event + event_projection + 해당 업무 이력/현재 값 |

수집 ACK를 받은 Python은 자기 송신 목록에서 그 사건을 제거한다. 이후 전달 책임은 수집 outbox에 남는다. 관제가 멈춰도 이미 수집 저장한 사건을 Python에 다시 생성하게 하지 않는다. 두 DB를 하나의 로컬 트랜잭션으로 묶지 않는다.

응답을 보낼 때까지의 성공을 말한다. 성공 응답이 유실되거나 응답 뒤 상대 DB 업데이트가 실패할 수 있어 **같은 사건 재전달과 중복 판정**을 사용한다. 예약·차체 위치를 반환하는 규칙은 아니다.

## 2. 원본과 동일 내용 판정

P0는 의미가 같은 JSON을 새로 직렬화해 비교하는 방식을 사용하지 않는다.

1. Python은 사건을 **한 번** UTF-8 JSON 한 줄로 직렬화하고 원본 바이트를 재전송 목록에 보관한다. LF를 제외한 문자열을 rawEvent라고 부른다.
2. eventSha256은 LF를 제외한 **원본 UTF-8 바이트의 SHA-256 소문자 64자리**다. 수집 DB는 원본 text와 해시, 파싱한 사건 정보를 함께 보관한다. 기존 표 초안의 payload_hash는 payload 일부가 아닌 이 전체 사건 원본 해시를 뜻한다. JSONB 조회값으로 원본 text를 재생성하지 않는다.
3. `(runId,eventId)` 또는 `(runId,sourceId,sourceSeq)`가 존재하면 **두 식별 관계가 모두 같고 해시와 원본 바이트도 같아야** 중복 성공이다. 같은 순번의 다른 eventId, 같은 eventId의 다른 순번/내용은 충돌이다.
4. 공백·키 순서·1과 1.0·문자 이스케이프를 바꾸면 다른 원본이다. 재전송 프로그램은 이를 ‘정리’하지 않는다. 해시가 같더라도 원본 비교를 생략하지 않는다.
5. 관제는 전달받은 rawEvent를 다시 파싱/검증하고 해시를 직접 계산한다. processed_event의 중복 판정에서도 원본 보존값을 비교한다. 이를 위한 raw_event.raw_json_text와 processed_event.raw_json_text를 추가한다.

원본이 다른 충돌 입력은 이미 저장된 정상 원본·처리 기록을 덮어쓰지 않는다. 수집 입력 거절 기록 또는 해당 outbox의 격리 근거에 남긴다. 새 ID를 붙여 자동으로 우회하지 않는다.

## 3. TCP 프레임과 수집 ACK

### 3.1 프레임

UTF-8(JSON)+LF 한 프레임의 최대 크기는 **65,536바이트(LF 포함)**다. rawEvent는 최대 65,535바이트다. BOM·CRLF·빈 줄·잘못된 UTF-8·JSON 중복 키·NaN/Infinity를 허용하지 않는다. JSON 문법 안의 이스케이프된 `\n`은 실제 프레임 줄바꿈과 구분한다.

- read 한 번에 여러 프레임이 있어도 각각 처리한다. 수신 조각의 전체 크기를 한 프레임의 크기로 판단하지 않는다.
- LF 전까지의 부분 버퍼가 65,535바이트를 넘으면 FRAME_TOO_LARGE로 연결을 닫는다. 이미 끝난 앞 프레임의 저장을 취소하지 않는다.
- 첫 바이트 이후 3초 안에 LF가 없으면 FRAME_TIMEOUT으로 정리한다. 부분 바이트 도착마다 제한 시간을 다시 늘리지 않는다.
- 연결 종료 시 LF 없는 잔여 입력은 저장하지 않는다. 완전한 앞 프레임만 결과를 유지한다.
- 오류 프레임은 ACK를 보낼 수 있으면 한 번 보낸 뒤 연결을 닫는다. 읽을 수 없는 식별자를 추측해 다른 사건을 확인 처리하지 않는다.

### 3.2 ACK의 전체 필드

응답도 UTF-8 JSON 한 줄+LF다. 최대 4,096바이트다. 아래 항목은 모두 필수이며 `?`는 null을 허용한다.

| 필드 | 자료형 / 규칙 |
|---|---|
| protocolVersion / kind | 정수 1 / INGESTION_ACK |
| runId, sourceId, eventId | 사건 ID 문자열? |
| sourceSeq | 사건 순번 정수? |
| eventSha256 | 원본 해시 문자열? |
| status | RECEIVED / DUPLICATE_RECEIVED / REJECTED / RETRY_LATER |
| code | 아래 오류 코드 또는 OK |
| receivedAt | 이번 프레임을 처음 본 수집 시각. 중복 성공은 최초 저장 기록의 시각 |
| committedAt | UTC 시각?; 성공 상태에서만 값이 있음 |
| retryAfterMs | 정수?; RETRY_LATER에서만 1~30,000 |

committedAt은 **이번 응답에서 저장이 이미 커밋됐음을 확인한 시각**이다. 새 저장의 COMMIT 성공 뒤, 또는 기존 커밋 행 확인 뒤 서버에서 얻는다. 중복 ACK의 committedAt은 바뀔 수 있으며 최초 커밋 순간을 DB에 정확히 저장했다는 뜻이 아니다. 최초 receivedAt은 원본 행에 보관한다. 지연 측정용 실제 COMMIT 반환 시점은 단조 시계로 따로 측정한다.

| status / code | 수집 동작 | Python 동작 |
|---|---|---|
| RECEIVED / OK | 원본+outbox 커밋 확인 후 응답 | 해당 사건 제거, 다음 순번 송신 |
| DUPLICATE_RECEIVED / OK | 기존 두 ID 관계·원본 일치 확인. 새 outbox 생성 금지 | 해당 사건 제거, 다음 순번 송신 |
| REJECTED / INVALID_UTF8·INVALID_JSON·INVALID_FRAME·FRAME_TOO_LARGE·FRAME_TIMEOUT | 프레임 거절, 성공 저장 없음 | 자동 무한 재시도 금지, 로컬 오류 기록·실행 중단 |
| REJECTED / SCHEMA_INVALID·UNSUPPORTED_SCHEMA·ID_CONFLICT·SEQUENCE_CONFLICT·SOURCE_CONFLICT | 잘못된 형식·버전·ID·run의 송신원 충돌 | 같은 사건을 고쳐 재사용하지 않음. 원인 해결 후 새 run |
| RETRY_LATER / DB_UNAVAILABLE·INGESTION_BUSY·OUTBOX_FULL·HISTORY_LIMIT·CLOCK_AHEAD·DIAGNOSTIC_UNAVAILABLE | 저장 성공을 확정하지 못함 또는 신규 접수 제한 | 원본 유지, 제한된 재시도 |

DB COMMIT 결과가 불명확한 경우에도 성공을 추정하지 않는다. 응답을 못 보내거나 RETRY_LATER를 보낼 수 있으며 Python은 원본을 유지한다. 실제로 커밋됐다면 다음 원본 재송신에서 중복 성공으로 확인한다.

입력 검증 → 기존 원본/충돌 확인 → **신규 사건**의 시각·대기/보관 상한 확인 → 원본+outbox 저장 순서다. 대기장이 꽉 차도 이미 저장된 원본의 중복 확인은 허용한다. 미래 발생 시각은 최초 receivedAt보다 최대 5초까지 허용하며 이를 넘는 신규 사건은 CLOCK_AHEAD다. 오래된 발생 시각은 지연된 사실일 수 있으므로 이 이유만으로 거절하지 않는다.

정상 파싱 사건의 ACK는 사건 ID 4개와 해시를 그대로 연결한다. JSON/식별자 파싱이 불가능하면 ID 4개를 전부 null로 두며, 전체 원본을 얻지 못했으면 해시도 null이다. Python은 version/kind/ID 4개/해시가 모두 일치하는 성공 ACK만 송신 완료로 인정한다. 상관없는 ACK나 깨진 응답은 목록을 지우지 않는다. 식별자를 읽지 못한 REJECTED는 연결의 오류로 기록하고 송신을 중단하며 특정 사건의 저장 성공으로 처리하지 않는다.

## 4. 내부 REST 요청과 관제 응답

### 4.1 요청

`POST /internal/v1/events/apply`, Content-Type: `application/json; charset=utf-8`. 수집 서비스만 호출하며 브라우저 API로 공개하지 않는다. 압축 요청은 P0에서 사용하지 않는다. 본문 최대 512KiB, 서버 응답 최대 8KiB다.

본문의 전체 필드는 `{protocolVersion,rawEvent,eventSha256,receivedAt}`다.

- protocolVersion=1. rawEvent는 앞 절의 **원본 한 줄을 문자열 값으로 담은 것**이다. LF는 담지 않는다. 외부 JSON 문자열 이스케이프를 풀면 원본 UTF-8 내용이 같아야 한다.
- eventSha256은 수집의 원본 해시이며 receivedAt은 원본 행의 최초 수신 시각이다. 재전달에서 이 세 값을 유지한다.
- rawEvent 내부의 사건 필드를 별도 JSON 객체로 다시 만들지 않는다. 이 방식은 두 언어의 직렬화 차이로 원본이 바뀌는 문제를 피한다.
- 해시 불일치·잘못된 외부 봉투는 INVALID_DELIVERY다. 입력의 사건 문법·업무 관계도 관제가 다시 확인한다.

### 4.2 응답의 전체 필드

| 필드 | 자료형 / 규칙 |
|---|---|
| protocolVersion / kind | 정수 1 / APPLICATION_RESULT |
| runId, sourceId, eventId, sourceSeq, eventSha256 | 요청 사건과 일치. 외부 요청을 읽을 수 없으면 ID와 해시 모두 null |
| status | APPLIED / DUPLICATE_APPLIED / REJECTED / RETRY_LATER |
| code | 아래 코드 |
| appliedAt | UTC 시각?; 성공에만 있음 |
| recordedAt | UTC 시각?; 성공 또는 영속 업무 거절 결과 기록에 있음 |
| retryAfterMs | 정수?; RETRY_LATER에서만 1~30,000 |

appliedAt/recordedAt은 처리 결과 행을 쓰면서 얻는 서버 시각이며, **실제 COMMIT 완료보다 앞설 수 있다.** 성공/영속 업무 거절 응답은 COMMIT 반환 뒤에만 보낸다. DUPLICATE_APPLIED는 기존 appliedAt/recordedAt을 유지한다. 실제 COMMIT 완료 지연은 별도 측정한다. DB에 기록한 시각과 COMMIT 순간을 같은 것으로 설명하지 않는다.

| HTTP | status / code | 저장과 수집 서비스 동작 |
|---|---|---|
| 200 | APPLIED / OK | 업무+처리 기록 커밋. outbox를 DELIVERED로 표시 |
| 200 | APPLIED / STALE_SNAPSHOT_RECORDED | 원본 투영/처리 기록만 보관하고 최신 물리 상태는 유지. 전달 성공 |
| 200 | APPLIED / FACT_ALREADY_RECORDED | 같은 업무 ID의 동일 사실이 이미 있음. 추가 집계 없이 새 보고 처리 기록만 남김 |
| 200 | DUPLICATE_APPLIED / 기존 성공 코드 | 동일 사건 재전달. 업무를 다시 적용하지 않음 |
| 422 | REJECTED / MODEL_INVALID·BUSINESS_ID_CONFLICT·INVALID_EVENT | 업무 변경 rollback 후 거절 근거 영속 기록. 해당 outbox 격리, run 전달 중단 |
| 409 | REJECTED / ID_CONFLICT·SEQUENCE_CONFLICT·SOURCE_CONFLICT | 기존 정상 기록 유지. 수집이 거절 근거와 원본을 영속 격리, run 전달 중단 |
| 409 | RETRY_LATER / RUN_NOT_READY·REFERENCE_NOT_READY·RUN_BLOCKED | 선행 등록/업무 참조 미확인 또는 이미 중단된 run. 성공 처리 기록 생성 금지 |
| 429 | RETRY_LATER / OPERATIONS_BUSY | 업무 슬롯 부족. 원본 유지·대기 |
| 503 | RETRY_LATER / DB_UNAVAILABLE·TEMPORARY_FAILURE | 저장 성공 미확인. 원본 유지·대기 |
| 400 / 413 / 415 | REJECTED / INVALID_DELIVERY·UNSUPPORTED_PROTOCOL / DELIVERY_TOO_LARGE / UNSUPPORTED_MEDIA_TYPE | 전달 프로그램/규격 문제. PAUSED_CONFIG. 사건을 업무 오류로 단정하거나 순번을 넘기지 않음 |

RETRY_LATER 응답은 Retry-After 헤더도 정수 초로 제공한다(ceil(retryAfterMs/1000)). 헤더의 초와 본문의 밀리초를 혼동하지 않는다. 헤더 의미는 [HTTP 공식 규격](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3)을 따른다. 경로 오류(404/405), 미지원 응답 버전/상태·응답 ID/해시 불일치와 HTTP 상태/본문 결과의 모순도 PAUSED_CONFIG다. 성공처럼 보이는 200의 본문이 깨졌으면 성공으로 확정하지 않고 제한된 재시도를 한다. 본문 없는 5xx는 일시 실패로 제한된 재시도를 한다.

거절 기록 저장도 실패하면 422를 확정하지 않는다. 503 또는 연결 오류로 처리한다. ID 충돌에서 기존 processed_event 행을 거절 행으로 바꾸지 않는다. 이 충돌 응답의 recordedAt은 충돌 근거인 기존 행의 기록 시각이며 수집 outbox에 수신 거절 결과와 해당 원본을 남긴다.

## 5. 전달 순서와 등록 선행

### 5.1 수집의 전달 진행

`ingestion_db.delivery_stream`을 추가한다. `(runId,sourceId)`를 식별하고 P0에서 runId도 UNIQUE로 두어 한 run의 송신원을 하나로 고정한다. 주요 값은 `next_source_seq`(초기 1), state, blocked_seq/reason, gap_started_at이다. 원본 접수와 진행 행 생성/송신원 결합은 같은 트랜잭션이다.

outbox.delivery_status는 PENDING / RETRY_WAIT / DELIVERED / QUARANTINED다. 전달 진행 state는 ACTIVE / RETRY_WAIT / GAP_WAIT / PAUSED_RETRY / PAUSED_GAP / PAUSED_DEPENDENCY / PAUSED_CONFIG / BLOCKED다. 보류된 뒤 사건도 원래 outbox에 남기며 따로 삭제/복제하지 않는다. 요청 중 상태는 단일 worker 메모리에만 있고, 재시작 시 원래 PENDING/RETRY_WAIT head를 확인한다.

- 기본 Python 송신 창은 **미확인 1건**이다. 수집 성공 ACK를 받기 전 다음 새 순번을 전송하지 않는다. 재접속은 같은 원본부터 재개한다.
- 수집의 전달 worker는 한 run에서 `next_source_seq` 한 건만 보낸다. 동시에 다음 건을 보내지 않는다. P0는 수집 서비스 한 인스턴스·worker 하나로 시작하고, 서로 다른 run은 순환 선택한다.
- 성공 결과를 확인한 뒤 **outbox DELIVERED + next_source_seq 1 증가**를 수집 DB의 같은 트랜잭션으로 저장한다. 이 저장이 실패하면 head를 다시 전달한다.
- HTTP 호출 중 수집 DB 트랜잭션/행 잠금을 붙잡고 있지 않는다. DB 조회/저장은 짧게 분리한다. P0 worker 단일성으로 해당 run의 병렬 발송을 막는다.
- 재시작은 DB 진행 행과 미전달 outbox에서 재개한다. auto-increment 행 ID의 최댓값이나 최대 sourceSeq를 재개 위치로 사용하지 않는다. 늦게 커밋한 낮은 순번을 건너뛰지 않는다.
- 기대 순번이 없고 더 높은 순번만 있으면 GAP_WAIT. 30초 뒤 PAUSED_GAP로 표시하고 뒤 순번을 보내지 않는다. 누락 원본이 들어오면 그 순번부터 다시 진행한다. 등록 사건을 만들어 끼워 넣거나 없는 데이터를 성공으로 표시하지 않는다.

### 5.2 관제의 업무 검증과 늦은 사실

RUN_STARTED를 반영한 뒤 해당 run의 BODY_REGISTERED·구성 참조를 처리한다. 차체를 참조하는 사건에는 먼저 등록한 차체/태그가 필요하다. BODY_ENTERED_CELL은 작업 ID의 소개이며 OPERATION_COMPLETED는 그 작업을 참조한다. TRANSPORT_ASSIGNED는 운송의 소개이고 STARTED/COMPLETED/CANCELLED는 그것을 참조한다. 초기 fixture도 시작 구성·차체 등록·필요 업무 소개를 생략해 실서비스로 전송하지 않는다.

초기 fixture에서 BODY_REGISTERED.initialLocation=CELL인 차체는 처음 검증된 스냅샷의 해당 셀/operationId로 초기 진행 작업을 소개할 수 있다. 이를 초기 작업의 참조 근거로 보관하되, 스냅샷의 completedCellIds·과거 점유 슬롯 ID로 완료/검사 fact를 자동 생성하지 않는다. 정상 Bay→셀 투입은 BODY_ENTERED_CELL로 작업을 소개한다.

SLOT_RESERVED는 같은 물리 전환에서 TRANSPORT_ASSIGNED보다 먼저 보고할 수 있으므로 **아직 없는 transportId의 소개를 허용**한다. 이력만 남기고 슬롯 카운터를 변경하지 않는다. SLOT_RELEASED/BODY_ENTERED_CELL도 하나의 인계 전환을 설명한다. 전체 스냅샷은 내부 소유 관계와 등록된 구성/차체를 검증하며 이력의 R/W를 별도로 더하지 않는다.

참조가 아직 없으면 임의 생성·PASS 가정 대신 REFERENCE_NOT_READY다. 최초 의존성 오류부터 30초 동안 제한된 재시도를 하고 해결되지 않으면 수집에서 PAUSED_DEPENDENCY로 보류한다. 시간이 지났다는 이유만으로 참조가 영원히 없다고 확정하거나 과거 사실을 삭제하지 않는다. RUN_BLOCKED는 즉시 중단 상태를 유지한다.

관제는 업무 처리 시 run별 DB 잠금으로 검증·변경을 직렬화한다. 수집의 정상 경로는 순번대로지만 **이미 등록 관계가 있는 늦은 원본의 수동 재전달**도 받을 수 있다. sourceSeq가 최신 스냅샷보다 낮다고 미반영 검사/작업 사실을 버리지 않는다. 오래된 스냅샷은 STALE_SNAPSHOT_RECORDED로 기록하고 현재 상태를 바꾸지 않는다. 최대 처리 순번을 연속 완료 커서로 오해하지 않는다.

같은 inspectionId/operationId의 동일 사실을 새 eventId로 보고하면 FACT_ALREADY_RECORDED이며 실적은 증가하지 않는다. 결과·차체·셀·원래 발생 시각 등 사실이 다르면 BUSINESS_ID_CONFLICT다. run·차체별 두 번째 최종 검사 ID도 P0에서는 충돌이다. 늦은 운송 사실은 이력으로 남기되 이미 완료/취소된 transport_history를 ASSIGNED로 되돌리지 않는다. 이력의 소개가 먼저 와야 한다는 검증은 유지한다.

## 6. 영구 거절과 격리

MODEL_INVALID 등 유효하게 식별된 업무 거절은 처리 실패 트랜잭션을 취소한 후, 별도 트랜잭션에서 processed_event(REJECTED)·오류 투영을 기록한다. 등록된 simulation_run의 processing_state는 BLOCKED로 둔다. RUN_STARTED 자체가 실패해 등록 행이 없어도 해당 run의 영속 REJECTED 기록을 중단 근거로 사용한다. 이미 처리한 동일 사건의 응답은 중단 여부 확인보다 먼저 판정해 재전달 결과를 유지한다.

수집은 422/409의 영구 거절을 확인하면 해당 outbox를 QUARANTINED로 기록하고 delivery_stream도 BLOCKED로 변경한다. 두 변경은 한 트랜잭션이다. 원본·해시·응답 code·거절 시각·시도 횟수를 보존한다. **next_source_seq는 증가시키지 않으며 뒤 사건도 자동으로 반영하지 않는다.** 다른 run은 계속 처리할 수 있다.

| 상황 | 후속 처리 |
|---|---|
| 일시 장애의 재시도 한도 도달 | PAUSED_RETRY. 원본·송신/전달 책임 유지. 원인 해결 후 같은 원본으로 명시적 재개 |
| 참조/순번 누락 | PAUSED_DEPENDENCY / PAUSED_GAP. 누락 원본/등록을 확인해 순서대로 재전달 |
| 업무 모순·같은 ID의 다른 내용 | QUARANTINED + BLOCKED. P0는 원인 수정 후 **새 run**으로 검증. 같은 ID의 payload 수정·무조건 건너뛰기 금지 |
| 미지원 버전·틀린 경로·응답 상관관계 오류 | PAUSED_CONFIG. 코드/설정 수정 후 같은 원본 재개 |

재전달은 자기 수집 DB의 보존 원본을 선택하고 ID/바이트를 유지한다. S05의 명시적 재개 도구는 현재 보류 head만 대상으로 run·순번·이전 상태·운영자·이유·시각을 기록한다. 이미 지나간 순번 범위의 수동 재전달 도구는 후속 범위다. 낮은 순번의 재전달은 정상 전달 커서를 되돌리거나 임의로 증가시키지 않는다. 영구 거절을 자동 재처리하는 버튼은 P0에 추가하지 않는다.

잘못된 TCP 입력은 정상 raw_event/outbox에 저장하지 않는다. 별도 구조화된 로컬 진단 파일(10MiB×3개 순환)에 시각·코드·읽힌 식별자·해시·최대 1KiB 원본 미리보기를 남긴다. 정상 저장한 원본의 보존과는 다른 제한된 진단 기록이다. 진단 기록 쓰기도 실패하면 DIAGNOSTIC_UNAVAILABLE 또는 연결 실패로 드러낸다. 관제에 전달 후 영구 거절된 **유효 수집 원본**은 DB에 전체를 보존하며 순환 로그로 대체하지 않는다.

## 7. 재시도와 대기 상한

정확한 기본값은 [전달 기본값 JSON](delivery-policy.json)이 기준이다. 설정으로 변경하면 이유·메모리/DB 용량과 검증 조건을 함께 기록한다.

| 항목 | P0 기본값 / 한도 도달 시 |
|---|---|
| Python TCP 연결 / ACK 대기 | 연결 2초, 프레임 송신 후 ACK 3초 |
| 부분 프레임 / ACK 크기 | 첫 바이트부터 3초 / 4KiB |
| TCP 동시 연결 / 입력 대기 | 8개 / 검증·저장 대기 128프레임 및 8MiB. 넘으면 INGESTION_BUSY |
| Python 미확인 송신 창 | 1건 |
| Python 사건 대기 | 최대 1,000건 및 64MiB 원본 바이트. 900건 또는 60MiB에서 물리 계산 일시 정지 준비 |
| 내부 HTTP 연결 / 응답 | 연결 1초, 연결 후 전체 응답 5초 |
| 내부 HTTP 본문 / 응답 | 512KiB / 8KiB |
| 미전달 outbox 전체 | 최대 5,000건 및 128MiB 원본 바이트. 격리·보류도 포함. 신규 접수 OUTBOX_FULL |
| 한 run 원본 보관 | 최대 50,000건 및 512MiB 원본 바이트 |
| 수집 전체 원본 보관 | 최대 250,000건 및 1GiB 원본 바이트. 도달 시 신규 접수 HISTORY_LIMIT |
| Python 한 head의 자동 시도 | 최초 포함 10회. 이후 로컬 PAUSED_RETRY |
| outbox 한 head의 자동 시도 | 최초 포함 20회. 이후 영속 PAUSED_RETRY |
| 순번 공백 / 의존성 대기 | 30초. 각각 PAUSED_GAP / PAUSED_DEPENDENCY |
| 신규 사건의 미래 시각 허용 | 5초. 초과 CLOCK_AHEAD |

DB 보관 바이트는 원본 text의 UTF-8 크기이며 인덱스/JSONB/DB 파일 크기를 포함한 디스크 총량이 아니다. 완료 원본을 자동 삭제하지 않는다. 상한을 올리거나 검증한 보관 절차를 마련하기 전에는 접수를 멈춘다. 실제 디스크/트랜잭션 자원 오류는 DB_UNAVAILABLE로 처리한다.

수집 admission은 P0 단일 저장 worker에서 직렬화하며 상한 검사와 새 원본/outbox 삽입을 같은 트랜잭션으로 처리한다. 동시 접수가 모두 ‘마지막 공간’을 승인하지 않도록 한다. 중복 접수는 새 공간을 소비하지 않는다.

재시도 간격은 실패 번호 k(첫 실패=1)에 대해 `min(500×2^(k−1), 30000)ms`다. 실제 실행은 0~10% 양의 jitter를 더하되 30초를 넘기지 않는다. 본문 retryAfterMs·Retry-After 헤더가 더 길면 그 시간을 지킨다. 서버가 30초보다 긴 대기를 요구하면 자동 루프 대신 PAUSED_CONFIG로 보류한다. 연결 오류·timeout·5xx·응답 유실은 성공 확정이 아니며 같은 원본을 유지한다.

시도 횟수·last_error·next_attempt_at·dependency_wait_started_at은 outbox에 영속 저장한다. HTTP 발송 전에 시도 증가를 먼저 저장하고, 이 저장이 실패하면 발송하지 않는다. 프로세스 재시작으로 횟수를 0으로 만들지 않는다. 조회/실행 도구의 명시적 재개에 한해 새로운 제한된 시도 묶음을 시작하고 재개 이유를 기록한다. 시험 예제의 jitter는 0으로 고정한다.

Python은 한 tick의 변경/사건을 확정하기 전에 대기 예산을 확인한다. 부족하면 **그 tick의 물리 변경을 확정하지 않고**, 남겨 둔 제어 사건 공간에 RUN_STATE_CHANGED(PAUSED/PAUSE_REQUEST)를 넣어 멈춘다. 이미 PAUSED라면 같은 변경 사건을 반복 생성하지 않는다. 슬롯·AGV·차체는 그대로 보유한다. PAUSED 중 큐가 가득한데 보고서를 계속 생성하지 않는다. 이 자동 정지에 한해 500건 및 32MiB 미만으로 배출되고 실패 head가 없으면 RESUME_REQUEST로 재개할 수 있다. 운영자의 의도적인 PAUSED는 자동으로 풀지 않는다. 물리 상태를 먼저 바꾼 뒤 사건만 버리는 방식은 사용하지 않는다. Python 메모리 자체를 잃는 종료는 P0의 무손실 보장 범위 밖이다.

진단에는 미전달 수/바이트·가장 오래된 receivedAt·전달 커서·중단 상태/순번/코드·누적 거절·재시도 수를 노출한다. TCP 연결 정상이나 최근 ACK만으로 GUI를 LIVE로 표시하지 않는다. 화면 판단 필드와 내부 진단 조회 경로는 S00-04의 [화면 계약](monitoring.md)에 확정했다.

## 8. 버전과 배포 호환

사건 schemaVersion과 전달 protocolVersion은 모두 정수 1만 지원한다. run 중 사건 버전을 바꾸지 않는다. 모르는 필드/상태/버전을 묵인하거나 성공처럼 처리하지 않는다. 지원하지 않는 Python 사건은 UNSUPPORTED_SCHEMA, 잘못된 내부 전달 버전은 UNSUPPORTED_PROTOCOL이다.

호환되지 않는 필드·의미 변경은 다음 버전의 별도 계약/예제로 만든다. 지금 v2를 지원하는 것은 아니다. 이후 변경은 **관제 수신 지원 → 수집 검증/전달 지원 → Python 새 run 전환** 순서로 준비하며, 기존 버전의 미전달 원본을 처리할 때까지 그 버전의 지원을 없애지 않는다. 보관 사건을 수정해 버전만 바꾸지 않는다.

## 9. 이번 작업의 확인 범위

[요청/응답 예제](examples/delivery-examples.json)와 [기본값](delivery-policy.json)을 [확인 도구](../../scripts/check_delivery_examples.py)로 확인한다. 실행 명령은 `python3 scripts/check_delivery_examples.py`다. 원본/해시·ID 연결, 응답 상태와 저장 시각/재시도 의미, HTTP 초/밀리초, 제한된 backoff와 프레임 크기만 확인한다.

이는 계약 자료의 확인이다. 실제 DB COMMIT/rollback, 커밋 후 응답 유실, 서버 재시작, 격리·순번 재개는 S03~S05에서 실제 DB/통신으로 확인했다. S08의 전체 장애 통합 검증은 후속이다. 가짜 DB·메모리 모형으로 실제 저장 보장을 통과했다고 기록하지 않는다. 웹개발을 처음 접하는 사람을 위한 사례는 [작업 3 해설](<../../docs/work-notes/작업 3. 저장 확인과 서비스 간 전달.md>)에 있다.

## 10. S05 내부 관측·명시적 재개 구현

S05는 기존 계약 필드를 유지한다. 단일 수집 인스턴스/worker가 발송 예약을 먼저 커밋하며, HTTP 중 수집 DB 트랜잭션을 유지하지 않는다. 응답 대기는 연결 시간을 포함한 전체 요청/응답 최대5초로 더 엄격하게 제한한다. 중단된 발송의 예약에는 5초 뒤 재시도 가능 시각이 남는다. 실제 발송 여부를 확정하지 못한 종료도 시도 예산은 소모하며, 재기동은 같은 원본/횟수/시각에서 이어 간다.

현재 attempt_count는 자동 시도 묶음(0~20), V2 total_attempt_count는 명시적 재개에도 유지하는 누적 예약 수다. last_attempt_at도 V2로 추가했다. 원본/해시는 변경하지 않는다. retryCount는 첫 예약 이후 추가 예약의 누적 수로서 발송 직전 종료를 포함할 수 있다. 네트워크에 정확히 몇 번 나갔는지를 확정하는 계측값으로 설명하지 않는다.

| 경로 | 구현 규칙 |
|---|---|
| GET /internal/v1/runs/{runId}/delivery-status | [화면 계약](monitoring.md) 16필드, no-store, 미등록404/읽기 실패503 |
| GET /internal/v1/runs/{runId}/outbox | afterSeq 기본0/안전정수, limit 기본50/최대200, status 생략 또는 PENDING/RETRY_WAIT/DELIVERED/QUARANTINED. 응답 최대512KiB |
| POST /internal/v1/runs/{runId}/delivery-resume | application/json UTF-8 정확한 {sourceSeq,operatorId,reason}, 최대2KiB, 현재 보류 head만 재개 |

outbox 응답은 {protocolVersion:1,runId,sampledAt,items,nextAfterSeq?}다. items는 eventId/sourceSeq/eventSha256/receivedAt/deliveryStatus/attemptCount/totalAttemptCount/lastAttemptAt/nextAttemptAt/dependencyWaitStartedAt/lastError/lastResponse/deliveredAt/quarantinedAt이다. 원본 전체를 목록에 싣지 않는다. 다음 페이지는 nextAfterSeq를 afterSeq로 사용한다. 조회 중 상태가 변경될 수 있으므로 확정 이력 fence로 사용하지 않는다.

재개는 PAUSED_RETRY/PAUSED_DEPENDENCY/PAUSED_CONFIG에 한정한다. sourceSeq는 현재 next_source_seq와 같아야 하며 head는 PENDING/RETRY_WAIT여야 한다. operatorId는 [A-Za-z0-9_-] 1~64자, 이유는 비공백 UTF-8 최대1024바이트다. 현재 시도 묶음·의존성 대기·다음 시각만 초기화하고 누적 횟수/오류 근거/원본/커서는 유지한다. delivery_action의 RESUME·이전 상태·운영자·이유·시각도 같은 트랜잭션에 저장한다. 응답은 {protocolVersion:1,runId,sourceSeq,state:ACTIVE,resumedAt,operatorId,reason}다. 커서 불일치/재개 불가409, 잘못된 입력400, 크기413, media415, DB실패503이며 no-store다.

BLOCKED/격리를 해제하거나 없는 번호를 성공으로 만들지 않는다. PAUSED_GAP은 누락 원본이 들어오면 해당 번호부터 자동 재개한다. `scripts/delivery-control.py`가 위 내부 경로를 호출한다. 사용자 인증이나 과거 범위 재전달 플랫폼을 추가한 것은 아니다.

실제 검증: [S05 수집 안내](../../services/ingestion-service/README.md), [최소 검증 결과](<../../docs/validation/최소 검증 시나리오와 도구.md>). 자동 전달60건과 응답 유실/실제 rollback/관제 DB 중단/순번·의존성/영구 거절/한도·재개/재시작을 필요한 묶음으로 확인했다.


## S07 상태 보고 연결

S07은 전달 protocolVersion=1과 Java 수집/관제 저장 구조를 유지한다. Python SourceSession은 의도적으로 PAUSED인 공장에서 물리 상태를 진행/자동 재개하지 않으면서 publish_snapshot 보고만 허용한다. 송신 대기 상한/READY 조건은 유지한다. 정상 등록 P0 원본556건의 양쪽 DB 바이트/해시·순서와 GUI를 확인했다. ACK는 계속 수집 저장 확인이며 단독으로 GUI 반영 성공을 뜻하지 않는다. [검증 기록](<../../docs/validation/최소 검증 시나리오와 도구.md>).
