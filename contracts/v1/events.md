# v1 사건 계약 — 식별자·시각·순번·payload

> 작업 ID: S00-02 · 결정일: 2026-10-05 · schemaVersion: 1  
> 상태: 사건 데이터 규격 확정. 실행 서비스와 전송 기능은 아직 미구현.

이 문서는 Python → 수집 서비스 → 관제 서비스가 함께 사용하는 **사건의 필드 규격**이다. [ADR-001](<../../docs/decisions/ADR-001-서비스 책임과 데이터 소유권.md>)의 책임과 기존 기술 스택을 유지한다. TCP 저장 확인·내부 REST 응답·재시도·격리·전달 순서는 S00-03의 [v1 전달 계약](delivery.md)에 확정했다. 화면용 REST/SSE 봉투와 신선도는 S00-04의 [화면 계약](monitoring.md)을 따른다. 이 사건 계약을 화면 SSE 응답으로 그대로 사용하지 않는다.

## 1. 읽는 방법과 파일

- 이 문서의 표는 v1의 필수 필드·자료형·허용값과 업무 관계를 정의한다. `?` 표시는 필드 생략이 아니라 **값에 null을 허용**한다는 뜻이다.
- 아래에서 정의한 객체의 필드는 모두 필수다. 별도로 ‘선택’이라고 표시한 측정값 키만 생략 가능하다. 빈 문자열을 null 대신 사용하지 않는다.
- 정의하지 않은 키, 사건 종류, 상태값은 v1 입력으로 허용하지 않는다. 버전 변경·호환 정책은 [전달 계약](delivery.md)을 따른다.
- [사건 종류별 JSON 예제](examples/event-catalog.json)는 서로 다른 예제 run의 17종 독립적인 필드 예제다. 배열 전체를 TCP로 보내거나, 배열 순서를 하나의 실행 이력으로 해석하지 않는다. 각 예제에서 생략한 등록·앞선 공정 맥락은 실제 송신 시 선행해야 한다.
- [버퍼 수명 NDJSON 예제](examples/buffer-lifecycle.ndjson)는 한 실행의 **일부 구간**이다. 앞선 실행·차체 등록·공정 이력은 생략했으며, 사건 순번 28~37을 유지한다. 첫 스냅샷부터 세 차체·모든 셀/Bay/차량을 함께 담는다. ASM-02는 처음 DOWN이며 도착 후 복구 사건을 거쳐 대기 차체를 받는다.
- 예제는 결정한 계약의 입력 자료다. 실제 공장이 실행됐다는 로그나 중복/장애 처리의 성공 증거가 아니다.

## 2. 식별자

모든 식별자는 문자열이며 대소문자를 구분한다. 앞뒤 공백·한글·공백 문자를 허용하지 않는다. 아래 형식은 전체 문자열에 적용한다. `N`은 0으로 채운 5~10자리 십진수다. 동일 종류의 번호는 run 안에서 재사용하지 않는다.

| 필드 | v1 형식 / 예 | 생성·참조 규칙 |
|---|---|---|
| runId | `run-YYYYMMDD-suffix`, 정규식 `^run-[0-9]{8}-[a-z0-9]{3,32}$` | Python이 새 실행마다 생성. 실제 실행 suffix는 UUID v4의 하이픈 없는 32자리 값. 날짜는 시작 UTC 날짜이며 달력상 유효해야 함. 예제의 `001`은 고정 fixture 전용 |
| sourceId | `^simulator-[0-9]{2,4}$`, `simulator-01` | P0는 run마다 송신 생산자 한 개. 같은 실행에서 변경하지 않음 |
| eventId | 소문자 UUID v4, `xxxxxxxx-xxxx-4xxx-[89ab]xxx-xxxxxxxxxxxx` | Python이 새 사건마다 생성. 재전송 시 보존. 전역 식별자로 사용 |
| cellId / equipmentId | `ASM-01`, `ASM-02`, `QC-01` | P0에서 값이 같음. run 구성에 등록된 셀만 사용 |
| bufferId | `BAY-` + cellId | 셀당 Bay 하나. 셀 작업 자리는 Bay 용량에 포함하지 않음 |
| slotId | bufferId + `-S1`~`-S4` | capacity가 3이면 S1~S3만 존재. run 중 슬롯 구성 고정 |
| vehicleId | `AGV-`/`AMR-` + 3~6자리 숫자 | 기본 AGV-001·002, AMR-001. 등록 kind와 접두어 일치 |
| bodyId / tagId | `body-N` / `tag-N` | run 안에서 1:1 고정. 번호를 같게 만들 수 있지만 **매핑은 BODY_REGISTERED가 기준** |
| unitId | bodyId와 동일한 문자열 | 작업·검사의 차체 참조. 별도 번호 생성하지 않음 |
| transportId | `transport-N` | 하나의 운송 할당~완료/취소에 고정. 다음 구간 운송에는 새 ID |
| reservationId | `reserve-N` | 차체 Bay 목적 운송에만 생성. transportId와 1:1. 완료 후에도 이력 ID 재사용 금지 |
| operationId | `operation-N` | 셀에서 차체 한 대를 처리하는 한 작업. 중단·복구로 새 작업을 만들지 않음 |
| inspectionId | `inspection-N` | 최종 검사 한 건. P0는 run의 차체당 한 번 |
| partsKitId | `kit-N` | 합성 부품 키트. bodyId/unitId로 변환하지 않음. 운송 할당에서 소개 |
| routeId | `^ROUTE-[A-Z0-9-]{1,48}$` | RUN_STARTED에 등록한 경로 |
| scenarioId | `^scenario-[a-z0-9-]{1,40}$` | 시나리오 변경 요청을 식별. 공장 객체 ID와 구분 |

공장 객체의 조회·업무 유일성 키는 `(runId, 해당 ID)`다. 다른 run에서 `body-00001`을 다시 사용해도 서로 다른 차체다. 수집 원본은 `(runId,eventId)`와 `(runId,sourceId,sourceSeq)` 각각 충돌을 확인한다. 관제의 작업/검사 유일성은 각각 `(runId,operationId)`·`(runId,inspectionId)`이며, 동일 차체의 두 번째 최종 검사도 정상으로 중복 집계하지 않는다. ID나 순번이 같고 내용이 다르면 새로운 사건으로 바꿔 저장하지 않는다. 응답과 원본 바이트/해시 비교 방식은 전달 계약을 따른다.

## 3. 공통 사건 봉투

| 필드 | 자료형 | 규칙 |
|---|---|---|
| schemaVersion | 정수 | 정확히 `1` |
| eventId | 문자열 | 위 UUID v4 형식 |
| runId | 문자열 | 위 실행 ID 형식 |
| sourceId | 문자열 | 위 송신원 형식 |
| sourceSeq | 정수 | 1~9,007,199,254,740,991. JavaScript에서 정확히 비교 가능한 범위 |
| eventType | 문자열 | 6절의 17종 중 하나 |
| occurredAt | UTC 시각 문자열 | 4절의 밀리초 정밀도 형식 |
| payload | 객체 | eventType에 해당하는 필드 규격 |

JSON에는 주석·NaN·Infinity·중복된 객체 키를 허용하지 않는다. 숫자 필드에 숫자 문자열이나 boolean을 넣지 않는다. 좌표/확률도 유한한 JSON 숫자여야 한다. 전송 시 UTF-8 JSON을 압축된 한 줄로 직렬화하고 LF로 끝낸다. TCP read 경계는 사건 경계가 아니다. 프레임 상한은 LF 포함 65,536바이트이며 상세 큐·초과 응답은 전달 계약을 따른다.

### 3.1 순번과 재전송

1. 새 run의 첫 사건은 `RUN_STARTED`, sourceSeq는 1이다.
2. **새 사건을 생성할 때** 1씩 증가한다. 스냅샷·측정·시나리오 변경도 사건이므로 같은 순번 공간을 쓴다. 사건이 발생하지 않은 tick에는 순번을 만들지 않는다.
3. 같은 tick의 여러 사건은 같은 occurredAt을 가질 수 있다. 순서는 sourceSeq로 구분한다. 작업/검사·예약/인계 사실을 먼저 기록하고 그 결과를 포함한 스냅샷을 뒤에 생성한다.
4. 재전송은 eventId·sourceSeq·occurredAt·payload를 포함한 사건 전체를 그대로 유지한다. 새 순번을 발급하거나 재전송 시각으로 occurredAt을 바꾸지 않는다.
5. 일시 정지·TCP 재연결·두 서버의 재시작은 Python의 순번을 초기화하지 않는다. Python 프로세스가 종료돼 메모리 모델을 잃으면 P0는 새 run을 시작한다. 이전 run 복원을 지원한다고 주장하지 않는다.
6. 생성 순서와 실제 수신 순서는 다를 수 있다. 관제의 **현재 상태**는 같은 run/source의 더 큰 sourceSeq를 가진 FACTORY_SNAPSHOT으로만 교체한다. 오래된 검사·작업 fact는 현재 상태와 별개로 처리한다.
7. 순번 공백만으로 영구 누락을 확정하거나 예약을 반환하지 않는다. 전달 계약의 누락 대기·run별 중단 정책을 따른다.

## 4. 시각과 시간

통신 시각은 `YYYY-MM-DDTHH:mm:ss.SSSZ` 형식의 **실제로 존재하는 UTC 시점**이다. 예: `2026-10-04T04:00:01.000Z`. 정확히 밀리초 3자리이며 지역 오프셋 문자열을 허용하지 않는다. 화면 표시는 Asia/Seoul로 변환한다.

| 시각/시간 | 생성 주체 | 의미 |
|---|---|---|
| occurredAt | Python | 사건 생성 시 UTC 벽시계 시각. 재전송에도 불변 |
| capturedAt | Python | 스냅샷을 얻은 시각. FACTORY_SNAPSHOT에서는 occurredAt과 같음 |
| createdAt / assignedAt / startedAt / completedAt / cancelledAt / inspectedAt | Python | 해당 등록·업무 전환의 원래 발생 시각. 아직 발생하지 않은 전환은 null |
| simElapsedMs | Python | 물리 계산의 누적 시간, 0 이상 정수. PAUSED 동안 증가하지 않음 |
| durationMs / remainingWorkMs | Python | 작업에서 실제 진행한 시뮬레이션 시간. 정지 시간과 통신 지연 제외 |
| receivedAt / committedAt | 수집 서비스 | 최초 수신 및 수집 저장 확인 단계의 서버 시각. Python 입력 봉투에 넣지 않음 |
| appliedAt | 관제 서비스 | 업무 처리 결과 행에 보관한 서버 시각. 성공 응답은 실제 COMMIT 뒤이며 시각 자체는 그보다 앞설 수 있음 |
| publishedAt | 관제 서비스 | 화면 발행 시각. 사건 occurredAt을 대체하지 않음 |

P0는 물리 계산을 실시간 1배속으로 진행한다. PAUSED 중 상태 보고의 occurredAt/capturedAt은 현재 벽시계로 생성할 수 있고 simElapsedMs만 멈춘다. 따라서 ‘정지’와 ‘보고가 오래됨’을 구분할 수 있다. 검사·품질 구간은 INSPECTION_COMPLETED.occurredAt으로 계산한다. 공정 소요시간은 두 벽시계 문자열을 단순히 빼서 만들지 않는다.

같은 프로세스의 경과 시간은 단조 시계로 측정한다. 프로세스 사이 지연 측정은 초기 단일 호스트 조건을 명시한다. 발생 시각만으로 사건 순서를 정하거나, 시계 변화로 sourceSeq를 되돌리지 않는다. 신규 사건의 미래 시각 허용은 전달 계약의 5초를 따르며 화면 신선도는 [화면 계약](monitoring.md)의 3/10초 경계와 진단 판정을 따른다.

## 5. 공통 객체와 상태

### 5.1 위치

`location`은 `{locationType, locationId}`다. 차체 현재 위치의 종류는 INPUT / CELL / BUFFER / VEHICLE / RESULT이며 각각 BODY-IN / cellId / bufferId / 차체 AGV ID / GOOD 또는 HOLD를 참조한다. BUFFER일 때 차체 객체의 locationSlotId로 실제 면을 함께 지정한다.

운송의 source/destination도 이 객체를 사용하되, source는 BODY 운송에서 INPUT 또는 CELL (traffic policyVersion>=2는 BUFFER도 허용), PARTS 운송에서 STORE(PARTS-STORE)다. destination은 BODY 운송에서 BUFFER 또는 RESULT (traffic policyVersion>=2는 CELL도 허용), PARTS 운송에서 PARTS_DOCK(PARTS-ASM-01/02)이다. 부품 도착 지점은 차체 셀 자리·Bay와 다른 공간이다. 경로의 양 끝과 운송의 위치가 일치해야 한다.

### 5.2 상태 열거형

| 대상 | 허용 상태 | 의미 |
|---|---|---|
| runState | RUNNING / PAUSED / FINISHED | 실행·일시 정지·종료 |
| 셀 state | IDLE / RUNNING / BLOCKED / DOWN | 빈 셀·공정 수행·완료 차체 보유·고장 |
| blockedReason | BUFFER_FULL / NO_VEHICLE / WAITING_PICKUP / null | BLOCKED에서만 비어 있지 않음. DOWN이면 이전 BLOCKED 원인은 resumeState와 함께 보존 가능 |
| 차체 status | WAITING / PROCESSING / WAITING_UNLOAD / IN_TRANSIT / COMPLETED | 진행 상태. COMPLETED는 최종 검사 완료로, 결과 구역 도착과 구분 |
| inspectionResult | NOT_INSPECTED / PASS / FAIL | 진행 상태와 별도. 검사 전은 PASS가 아님 |
| 슬롯 status | FREE / RESERVED / OCCUPIED | 빈 면·도착 약속·실제 대기 |
| 차량 state | IDLE / TO_PICKUP / LOADING / MOVING / UNLOADING / RETURNING | 픽업 전 빈 이동과 적재 이동 구분 |
| 차량 kind / cargoType | AGV 또는 AMR / BODY 또는 PARTS | AGV는 BODY, AMR은 PARTS 운송 |
| 운송 status | ASSIGNED / IN_TRANSIT / COMPLETED / CANCELLED | 출발 전 할당·적재 운송·인계 완료·출발 전 취소 |

검사 완료 차체는 status=COMPLETED를 유지하며 locationType=VEHICLE일 수도 있다. 실제 이동 여부는 위치/운송에서 읽는다. DOWN 상태의 resumeState는 IDLE/RUNNING/BLOCKED 중 이전 상태이고, 정상 셀에서는 null이다. DOWN이 아니고 BLOCKED도 아닌 셀의 blockedReason은 null이다.

### 5.3 운송 객체 T

네 TRANSPORT 사건의 payload와 스냅샷 activeTransports는 동일한 다음 필드를 사용한다.

| 필드 | 자료형 / 규칙 |
|---|---|
| transportId, vehicleId, routeId | 등록된 ID 문자열 |
| cargoType, status | 위 열거형 |
| bodyId, partsKitId | 문자열?; BODY는 bodyId만, PARTS는 partsKitId만 값이 있음 |
| source, destination | 위치 객체 |
| reservationId, slotId | 문자열?; BODY+BUFFER 목적지는 둘 다 필수, BODY+RESULT 및 PARTS는 둘 다 null |
| assignedAt | UTC 시각 |
| startedAt, completedAt, cancelledAt | UTC 시각? |
| cancelReason | `SCENARIO_CANCEL`, `PRIORITY_REDISPATCH`, `DIRECT_DELIVERY_AVAILABLE` 또는 null |

ASSIGNED는 시작/완료/취소 시각이 null이다. IN_TRANSIT은 startedAt만 값이 있다. COMPLETED는 startedAt·completedAt이 있고 cancelledAt/cancelReason은 null이다. CANCELLED는 startedAt/completedAt이 null이고 cancelledAt·cancelReason이 있다. 각 전환 시각은 assignedAt 이후이며 해당 사건의 전환 시각은 occurredAt과 같다. 같은 물리 tick에 시작과 종료가 있으면 시각이 같을 수 있다. 취소는 아직 차체가 출발지에 있는 ASSIGNED에서만 가능하다.

`PRIORITY_REDISPATCH`는 traffic 구성에서 아직 적재를 시작하지 않은 INPUT 픽업 배차를 취소하고 완료된 CELL의 픽업으로 전환할 때 사용한다. 기존 슬롯 예약을 해제하고 새로운 transportId로 배차하며, 미투입 차체는 이후 자동 배차 대상으로 남는다. 사용자 시나리오 취소와 달리 SCENARIO_CHANGED를 발생시키지 않는다.

## 6. 사건 17종의 payload

아래 표의 모든 필드가 필수다. T와 공장 구성/스냅샷의 내부 필드는 해당 절에 정의한다.

| eventType | 필드와 자료형 | 업무 의미 / 추가 규칙 |
|---|---|---|
| RUN_STARTED | seed: 정수, config: 공장 구성 | run 최초 사건. seed 0~2,147,483,647 |
| RUN_STATE_CHANGED | previousState, state: runState, reason: 문자열 | 이유는 PAUSE_REQUEST / RESUME_REQUEST / DRAINED. 같은 상태로의 변경은 생성하지 않음 |
| FACTORY_SNAPSHOT | 8절의 스냅샷 객체 | 전체 현재 상태. 누적 생산/품질 카운터를 fact 대용으로 넣지 않음 |
| BODY_REGISTERED | bodyId, tagId, modelCode, specCode: 문자열, createdAt: 시각, initialLocation: 위치 | createdAt=occurredAt. 정상 투입은 INPUT/BODY-IN. 초기 검증 fixture만 CELL/BUFFER에서 시작 가능하며 초기 상태와 일치 |
| SLOT_RESERVED | reservationId, transportId, bufferId, slotId, bodyId, vehicleId: ID | AGV와 목적지 슬롯을 함께 확보한 전환의 이력. 아직 차체 위치는 출발지 |
| SLOT_RELEASED | bufferId, slotId, bodyId: ID, reservationId, transportId: ID?, reason: 반환 사유 | BODY_ENTERED_CELL, CANCEL_BEFORE_DEPARTURE 또는 정책 2의 BODY_PICKED_UP. 초기 점유 fixture의 과거 예약/운송이 없을 때만 두 ID 모두 null |
| BODY_ENTERED_CELL | bodyId, cellId, operationId: ID, bufferId, slotId: ID? | 새로운 공정 작업 ID 연결. 기존 Bay 인계는 bufferId/slotId 필수. 정책 2의 AGV 직접 인계는 두 필드 모두 null |
| TELEMETRY_UPDATED | entityType: EQUIPMENT/VEHICLE, entityId: ID, measurements: 객체, position: 좌표? | EQUIPMENT는 position=null, measurements에 선택 키 temperatureC(숫자)·cycleTimeMs(0 이상 정수) 중 1개 이상. VEHICLE은 measurements={}와 position={x,y}. 현재 물리 상태는 이 사건으로 덮지 않음 |
| EQUIPMENT_STATE_CHANGED | cellId, equipmentId: ID, previousState, state: 셀 state, bodyId: ID?, reason: 문자열 | cellId=equipmentId. reason은 WORK_STARTED / WORK_COMPLETED / BUFFER_FULL / NO_VEHICLE / WAITING_PICKUP / PICKUP_COMPLETED / FAILURE_INJECTED / RECOVERED. 같은 상태 변경은 생성하지 않음 |
| OPERATION_COMPLETED | operationId, cellId, equipmentId, unitId: ID, durationMs: 0 이상 정수 | cellId=equipmentId, unitId=bodyId. 조립/검사 작업 완료이며 배출 완료가 아님 |
| INSPECTION_COMPLETED | inspectionId, equipmentId, unitId: ID, result: PASS/FAIL, defectCode: 문자열? | equipmentId=QC-01. PASS면 defectCode=null, FAIL이면 SIM_DEFECT_01. inspectedAt으로 occurredAt 사용 |
| TRANSPORT_ASSIGNED | T | status=ASSIGNED, assignedAt=occurredAt |
| TRANSPORT_STARTED | T | status=IN_TRANSIT, startedAt=occurredAt. 출발지 차체 제거+AGV 적재 완료 |
| TRANSPORT_COMPLETED | T | status=COMPLETED, completedAt=occurredAt. Bay에서는 RESERVED→OCCUPIED이며 슬롯 반환 아님 |
| TRANSPORT_CANCELLED | T | status=CANCELLED, cancelledAt=occurredAt. BODY의 출발 전 취소. SCENARIO_CANCEL, traffic 구성의 PRIORITY_REDISPATCH, 정책 2의 DIRECT_DELIVERY_AVAILABLE |
| SCENARIO_CHANGED | scenarioId, action, targetId: 문자열, parameters: 객체 | 아래 action별 규격. 대상이 없는 공장 전체 설정은 targetId=runId |
| RUN_FINISHED | reason: DRAINED/MODEL_ERROR, uniqueEventCount: 양의 정수 | 마지막 새 사건. P0 단일 생산자에서 자신을 포함한 생성 사건 수=sourceSeq. 재전송 횟수와 다름 |

modelCode/specCode는 공백 없는 영문 대문자·숫자·하이픈으로 1~32자리이며 예는 DEMO-EV-A / STANDARD다. 자유 형식 메시지와 운영자 메모를 사건 필드에 추가하지 않는다.

SCENARIO_CHANGED의 parameters는 다음과 같이 고정한다.

| action | targetId | parameters |
|---|---|---|
| CELL_DOWN / CELL_RECOVER | cellId | `{}` |
| TRANSPORT_DELAY | transportId | `{additionalDelayMs: 0 이상 정수}`; 실제 안전 취소를 뜻하지 않음 |
| QUALITY_PATTERN | runId | `{results: PASS/FAIL 배열}`; 비어 있지 않은 결과 배열 |
| CANCEL_BEFORE_DEPARTURE | transportId | `{}`; 취소 가능 조건은 5.3절 |

사건을 만드는 물리 전환과 상태 보고는 Python 한 곳의 책임이다. SLOT_RESERVED와 TRANSPORT_ASSIGNED는 한 할당 전환의 서로 다른 설명이고, SLOT_RELEASED와 BODY_ENTERED_CELL도 한 인계 전환의 설명이다. 서버에서 이 두 사건을 각각 더해 슬롯을 두 번 증감하지 않는다.

## 7. RUN_STARTED 공장 구성

config의 필드는 다음과 같다. 배열 안 ID는 해당 종류에서 중복될 수 없다. 수집은 형태/값 범위를 검사하고, 관제는 구성 등록과 참조 관계를 검사한다.

| 필드 | 형태와 P0 규칙 |
|---|---|
| tickMs / snapshotIntervalMs | 양의 정수, 초기 100 / 500. snapshotIntervalMs는 tickMs의 배수 |
| speed | 숫자, P0에서 1 |
| maxBodies | 정수 1~100. 신규 투입 상한이지 과거 완료 차체 삭제 기준이 아님 |
| failProbability | 0~1 유한 숫자, 초기 0.01. 지정 결과 배열을 쓰는 검증과 구분 |
| locations | `{locationType,locationId,x,y}` 배열. BODY-IN, 셀 3개, Bay 3개, GOOD/HOLD, PARTS-STORE, PARTS-ASM-01/02를 등록. x/y는 유한 좌표 |
| equipment | `{cellId,equipmentId,bufferId,workDurationMs}` 배열. ASM-01/02·QC-01 전부 포함. 대표 설비 ID=셀 ID, 작업 시간 양의 정수 |
| buffers | `{bufferId,cellId,capacity,slotIds}` 배열. capacity 2~4, slotIds 길이=capacity, S1부터 순서대로 지정 |
| vehicles | `{vehicleId,kind,home,initialPosition}` 배열. 기본 AGV 2대/AMR 1대. home은 등록된 위치, initialPosition={x,y} |
| routes | `{routeId,cargoType,source,destination,points,travelDurationMs}` 배열. 양 끝 등록 위치 및 points의 처음/끝 좌표 일치. points는 좌표 2개 이상, 시간 양의 정수 |

차체 경로는 BODY-IN→BAY-ASM-01, ASM-01→BAY-ASM-02, ASM-02→BAY-QC-01, QC-01→GOOD/HOLD다. 부품 경로는 PARTS-STORE→PARTS-ASM-01/02다. 빈 차의 픽업 이동·귀환은 이 구성의 좌표를 사용한 단순 모델로 구현하며, 차체 예약을 추가 소비하지 않는다. 경로 충돌 방지와 교차로 제어를 정의한 계약이 아니다.

## 8. FACTORY_SNAPSHOT의 전체 필드

payload는 `{runState,capturedAt,simElapsedMs,equipment,buffers,bodies,vehicles,activeTransports}`다. RUN_STARTED와 같은 등록 셀·Bay·차량을 전부 포함한다. bodies는 그 run에서 등록한 전체 차체(완료 포함)를 보존한다. activeTransports에는 ASSIGNED/IN_TRANSIT만 포함하고 완료/취소 이력은 사건에서 조회한다. 배열 자체를 사건별 증감 조각으로 사용하지 않는다.

### 8.1 셀 요소

`{cellId,equipmentId,state,resumeState,bodyId,operationId,remainingWorkMs,blockedReason,destinationCellId}`

- IDLE은 bodyId/operationId/destinationCellId=null, remainingWorkMs=0이다.
- RUNNING은 bodyId/operationId가 있고 차체 위치 CELL 및 PROCESSING과 연결된다.
- BLOCKED는 완료 차체와 operationId를 보유하고 remainingWorkMs=0이다. 목적지 만석·차량 없음·픽업 대기를 구분한다. 최종 QC 배출의 destinationCellId는 null이며 출구는 운송 목적지에서 읽는다.
- DOWN은 차체·남은 작업과 resumeState를 보존한다. 셀 하나가 두 차체를 보유할 수 없다.

### 8.2 Bay와 슬롯 요소

Bay: `{bufferId,cellId,capacity,waitingCount,reservedInboundCount,availableSlots,slots}`

슬롯: `{slotId,status,bodyId,vehicleId,transportId,reservationId}`

- FREE: 네 소유 ID 모두 null.
- RESERVED: 네 소유 ID 모두 값이 있고, 같은 활성 BODY 운송의 목적지/차체/차량/예약과 일치. ASSIGNED 또는 IN_TRANSIT에 대응한다.
- OCCUPIED: bodyId가 있고 vehicleId=null. 그 차체는 BUFFER/해당 Bay/해당 slotId에 실제로 있다. transportId/reservationId는 원래 인계의 이력 ID이며 둘 다 값이 있거나 초기 fixture에서 둘 다 null이다. **활성 예약 수에 포함하지 않는다.**
- `W=OCCUPIED 수`, `R=RESERVED 수`, `A=C-W-R`, slots 길이=C, 0≤W+R≤C다. 카운터와 목록이 다르면 잘못된 모델 보고다.
- 자기 슬롯을 이미 예약한 운송은 A=0이어도 진행할 수 있다. A=0은 다음 신규 예약을 막는다.

### 8.3 차체 요소

`{bodyId,tagId,modelCode,specCode,status,locationType,locationId,locationSlotId,currentCellId,completedCellIds,nextCellId,transportId,reservationId,inspectionResult,inspectedAt,lastObservedAt}`

- completedCellIds는 완료한 셀을 공정 순서대로 중복 없이 기록한 배열이다. nextCellId는 다음 공정 셀 또는 최종 검사 후 null이다.
- currentCellId는 locationType=CELL에서만 해당 셀 ID이고 다른 위치에서는 null이다. locationSlotId는 BUFFER에서만 해당 슬롯 ID다.
- transportId/reservationId는 **현재 활성** 운송/예약이다. 예약만 잡힌 차체의 위치는 여전히 INPUT/CELL이고, 실제 픽업 후 VEHICLE이다. 완료/취소 후 이 두 참조를 비운다.
- BODY+RESULT 운송은 transportId만 있고 reservationId=null이다. COMPLETED는 PASS/FAIL과 inspectedAt을 갖고, 검사 전에는 NOT_INSPECTED/inspectedAt=null이다.
- tagId 연결은 등록과 같아야 한다. lastObservedAt은 해당 스냅샷 capturedAt이다. 한 차체는 셀·Bay·적재 AGV·경계 장소 중 정확히 한 곳에 있다.

### 8.4 차량 요소와 운송 연결

차량: `{vehicleId,kind,state,position,bodyId,partsKitId,transportId}`, position=`{x,y}`

ASSIGNED 운송의 TO_PICKUP/LOADING 차량은 아직 적재하지 않아 bodyId/partsKitId=null이다. IN_TRANSIT 운송의 MOVING/UNLOADING 차량은 해당 화물을 하나만 보유한다. IDLE/RETURNING은 화물/transportId가 null이다. 동일 AGV나 차체를 두 활성 운송에 할당하지 않는다. AMR 화물은 partsKitId만 사용한다.

activeTransports의 각 요소는 5.3절 T다. RESERVED 슬롯과 활성 BODY+BUFFER 운송은 서로 정확히 하나씩 대응한다. 입력/셀에서 픽업을 기다리는 차체도 이 예약에 포함한다. BODY+RESULT·PARTS 운송에는 예약/슬롯이 없다. 스냅샷에서 셀·슬롯·차량의 보유 참조와 차체의 단일 위치를 서로 확인한다.

## 9. 최소 확인과 후속 범위

이번 작업의 검증은 JSON/NDJSON 형식과 예제의 식별자·필수 항목·참조 관계, 버퍼 수명 구간의 물리 일관성에 한정한다. [예제 확인 스크립트](../../scripts/check_contract_examples.py)는 이 계약에 필요한 대표 오류만 확인하는 표준 라이브러리 도구다. 모든 운영 입력을 검증하는 수집/관제 구현이나 범용 JSON Schema 검증기가 아니다. 실행 명령은 `python3 scripts/check_contract_examples.py`다.

JSON 구조의 표준 키워드로 기계 판독 스키마를 만드는 방법은 [JSON Schema 공식 규격](https://json-schema.org/draft/2020-12/json-schema-validation)을 참고할 수 있다. 이번 산출물의 필드 규격은 이 문서의 표이며 별도 JSON Schema 파일이나 라이브러리 도입은 하지 않는다. 검증 도구는 [최소 검증 계획](<../../docs/validation/최소 검증 시나리오와 도구.md>), 실제 입력 검증 구현은 S03/S04에서 진행한다.

S00-03에서 ACK/내부 REST 필드, ID·내용 충돌의 비교 방식, 순서/등록 선행 처리, 재시도·격리·큐/프레임 상한·호환성 정책을 [v1 전달 계약](delivery.md)에 확정했다. 본 문서에서 S00-03으로 미뤘던 항목은 그 계약을 따른다. 수집 committedAt은 이번 응답에서 커밋을 확인한 시각이다. S00-04에서 외부 REST/SSE DTO, 신선도·반영 지연·조회 시간 구간은 [화면 계약](monitoring.md), 검증 도구는 최소 검증 계획에 확정했다. 구체적인 사건 데이터는 본 문서를 기준으로 사용한다. 쉬운 작업 설명은 [작업 2 해설](<../../docs/work-notes/작업 2. 식별자와 사건 데이터 규격.md>)에 있다.

## 선택적 3D 교통 확장 (2026-10-10)

기존 v1 실행과 이벤트는 계속 유효하다. 새 교통 실행을 보내기 전에 수신·운영 서비스의 확장 validator를 함께 배포한다. 기존 schemaVersion=1 필드를 바꾸지 않고 아래 선택적 필드만 허용한다.

- `RUN_STARTED.payload.config.traffic`: `policyVersion: 1, 2, 3 또는 4`, `vehicleRadius >= 24` (정책 2 이상은 30 이상), `clearance >= 3`, `bounds: {minX,minY,maxX,maxY}`, `obstacles: [{id,minX,minY,maxX,maxY}]`. 직사각형 좌표는 유한 수, min < max, 장애물 ID 중복 금지, 1~32개다. 단위는 기존 모델 좌표다.
- `FACTORY_SNAPSHOT.payload.vehicles[].traffic`: `path: [{x,y},...]` (2~128점), `elapsedMs` (0 이상 정수), `durationMs` (양의 정수), `waiting` (boolean). `elapsedMs <= durationMs`. 차량 위치와 동일한 Python 운동 모델의 확정 경로·진행량이다. 경로 미확정·정지 시 현재 위치를 두 번 넣고 진행량 0을 보낸다.
- 예약 경로는 현재 위치부터 목적지까지 남은 경로의 통행 영역을 독점한다. 이미 지난 구간은 다음 tick부터 해제하되, 같은 tick에서 지나간 영역은 모든 차량의 갱신이 끝날 때까지 보호한다. 다른 차량의 현재 안전영역과 예약 경로를 침범하지 않는 경로만 승인하며, 공간이 없으면 정지한다. 서로 목적지를 점유한 경우 비어 있는 양보 지점을 탐색한다.
- 슬롯 예약과 통행 예약은 서로 다른 개념이다. 기존 `reservationId`, `W/R/A` 및 소유권 규칙은 변경하지 않는다. 차체 인계는 접안 후 기존 상태 전환으로 표현한다.
- 운영 서비스는 이 정보를 그대로 전달한다. 프런트에서 경로를 새로 계산하거나 과거 실행에 충돌 회피가 있었던 것처럼 보정하지 않는다.
- 이 확장은 운동학적 충돌 회피이며 강체 충격·가속도·조향 한계의 물리 재현을 주장하지 않는다.


### 3D 교통 정책 2: 직접 공정 투입과 대기 Bay 운반

직접 공정 투입은 `traffic.policyVersion=2`부터 지원한다. 기존 정책 1과 traffic 없는 실행의 설정·경로·인계 규칙은 그대로 읽는다.

- 정책 2에는 기존 경로 7개에 BODY-IN→ASM-01, ASM-01→ASM-02, ASM-02→QC-01, 각 BAY→대응 CELL의 BODY 경로 6개가 추가된다.
- 비어 있고 정상인 셀에 다른 입고 운송이 없으며 앞선 Bay 대기/입고가 없으면 목적지는 CELL이다. 셀이 사용 중·고장·입고 예약 상태면 여유 슬롯을 확보해 BUFFER로 보낸다. Bay 차체는 AGV가 픽업하여 CELL로 운반한다.
- CELL행 활성 운송 자체가 해당 셀의 입고 예약이다. 같은 셀로 활성 운송을 중복 배정하지 않는다. CELL행 운송의 reservationId/slotId는 null이고 Bay 슬롯을 소비하지 않는다. 도중 셀이 고장 나면 AGV에 적재를 유지하고 복구 후 인계한다.
- AGV가 CELL 접안 위치에서 하차를 끝내야 차체 소유가 CELL로 옮겨지고 작업이 시작된다. `BODY_ENTERED_CELL`의 bufferId/slotId는 이 경우 모두 null이다. 관제는 정책 2 및 해당 CELL로 실제 운송된 이력을 확인한다.
- Bay 슬롯은 셀 도착 시점이 아니라 Bay에서 AGV가 차체를 적재하는 순간 `SLOT_RELEASED(reason=BODY_PICKED_UP)`으로 반환한다. 사건은 이전 Bay 입고의 transportId/reservationId를 참조한다.
- 모델 외형은 정책 1 대비 1.25배다. vehicleRadius는 30 이상, clearance는 3 이상이다. 확대한 설비·Bay·보관 구역은 obstacles와 일치하며 접안 공간·외곽 경계·개별 주차 위치도 조정한다.

정책 2에서는 적재 직전에도 목적지를 재평가한다. 설비가 비었고 다른 선행 Bay 대기가 없으면 기존 Bay행 ASSIGNED 운송을 `DIRECT_DELIVERY_AVAILABLE`로 취소하고 슬롯 예약을 반환한 뒤 CELL행 운송을 새로 배정한다. 적재 후 운송을 취소하거나 차체 위치를 순간 변경하지 않는다.

### 3D 교통 정책 3: 통로 예약과 운동 제약

정책 3은 `traffic.policyVersion=3`으로 구별한다. 현재 새 실행 기본값은 아래 정책 4다. 정책 1·2 및 traffic 없는 기존 실행은 기존 배치·운동·인계 규칙으로 재생한다. 정책 2의 직접 CELL 인계와 물리적 Bay 픽업 규칙은 정책 3에도 적용한다.

- 정책 3의 `traffic`에는 `lanes: [{start:{x,y}, end:{x,y}}]`와 `holdingPoints: [{x,y}]`가 추가된다. lanes는 방향성이 있는 축 정렬 구간이고, 양방향 구간은 반대 방향 항목을 함께 둔다. 현재 공장용 통로망을 설정에 저장하여 과거 배치를 재현한다.
- 기본 공장: CELL 접안 y=100, 동쪽 주행 y=180, 서쪽 주행 y=260, BAY 접안 y=340. BAY 실물은 접안점 뒤쪽에 있다. 부품 접안 y=510, STORE y=560, 차량 주차는 (-90,260), (-90,420), (-90,760)이다. 경계 maxY=820으로 확장한다. 접안점과 주행선 중심의 80 간격은 차량 간 기준 63보다 크다.
- 차량의 `traffic`에 `heading:number`와 `segments:[]`를 추가한다. heading은 모델 평면의 +x 기준 라디안이다. 정지 시에도 마지막 방향을 보존한다. 3D y축 회전에는 부호를 반대로 사용한다.
- 각 segment 필드: `turnMs`(0 이상 정수), `travelMs`(양의 정수), `rampMs`(0 초과, travelMs/2 이하), `initialHeading`, `heading`(유한 라디안), `peakSpeed`(0~0.0375 모델 좌표/ms). segment 수는 path 점 수-1이며 모든 turnMs+travelMs의 합은 durationMs다. 정지·상하차 상태는 segments=[]다.
- 회전은 최단 각도 방향으로 제자리에서 수행한다. 정확히 반대 방향은 -π를 택한다. 이동은 선형 가속→정속→선형 감속의 사다리꼴 속도 곡선이며 각 구간 끝에서 정지한다. 최고 속도 37.5 모델 좌표/s, 가속도 상한 75 모델 좌표/s², 회전 속도 상한 120°/s다. 모델 좌표를 미터 단위로 해석하지 않는다.
- path는 전체 계획 경로이며, 허가된 이동 거리나 점유 영역 자체를 뜻하지 않는다. 다음 한 구간만 통행 예약하고 대기 중 elapsedMs는 증가시키지 않는다. 현재 tick의 예약은 모든 차량의 갱신이 끝날 때까지 보호한다.
- A*는 거리와 정차 비용, 현재 통행 충돌의 예상 대기 비용을 사용한다. 한 주행 구간 중간에는 경로를 바꾸지 않는다. 3초 이상 막힌 정차 지점에서만 통행 가능한 대체 경로를 검토한다. 경로 변경 비용 75 모델 좌표(최대 속도 2초)를 추가하여 작은 이득 때문에 바꾸지 않고, 교착은 지정 holdingPoint로 양보하여 해소한다. 경로가 항상 존재하거나 모든 임의 배치의 교착이 해소된다는 보장은 하지 않는다.
- 정책 3에서는 이동/회전 도중 빈 복귀 차량의 재배차와 선행 입력 작업 취소를 하지 않는다. 다음 정차 노드에서 다시 평가한다. 명시적 운송 취소도 정차 노드 또는 상차 대기 때만 허용한다.
- 충돌 검사는 적재물까지 포함하는 반경 30의 원형 안전 영역으로 수행한다. 이는 충돌 없는 평면 운동 모델이며, 타이어 접지·충격·센서 인식 모델은 포함하지 않는다.

### 3D 교통 정책 4: 가까운 작업 연결과 접안 후진

새 `--traffic` 실행의 기본값은 `traffic.policyVersion=4`다. 정책 3의 메시지 필드·안전거리·구간 예약·가감속 상한을 유지한다.

- 주행 통로는 양방향이며 교차/대향 차량의 안전 영역이 겹치는 구간은 동시에 허가하지 않는다. 직선 위 중간 노드는 하나의 운동 구간으로 합쳐 불필요한 정차를 없앤다.
- 빈 차량이 재료 접안점에서 출발하는 첫 구간에 한해, 길이 100 이하이고 진행 방향과 차체 방향의 차이가 90도를 넘으면 후진한다. 적재 상태(MOVING)는 후진하지 않으며 정지 회전 후 전진한다. 교차로·중간 구간 후진도 금지한다. 후진 최고 속도는 18.75 모델 좌표/s다. `segments.heading`은 차체 방향이며 이동 벡터와 반대일 수 있다. 위치 보간은 path, 차체 회전은 heading을 사용한다.
- 공정 인계 후 바로 IDLE로 현장 대기한다. 남은 작업이 8초 이하이면 해당 공정 완료 픽업을 기다린다. 고장/긴 작업은 이 대기 예약에서 제외한다. 출고 접안점만 가까운 개별 대기점으로 비운다. 다른 배정 차량의 목적지를 막는 IDLE 차량도 지정 대기점으로 비킨다.
- 기본 출고 대기점은 AGV-001 (780,260), AGV-002 (780,340)이다. 기존 차량 초기 주차점은 유지한다. 과거 실행의 규칙은 policyVersion으로 보존한다.
- 개발 관제의 중단 명령은 소유한 로컬 Python 실행에 SIGTERM을 보낸다. 정상 생산 완료 사건 RUN_FINISHED를 만들지 않는다. 실행기 STOPPED와 생산 FINISHED는 구별한다.

- 모든 차체가 RESULT이고 활성 운송이 없으며 차량이 정지한 뒤, AGV를 한 대씩 최종 복귀시킨다. (845,650) → (0,650)의 외곽 통로를 지나 각 initialPosition으로 복귀한다. 외곽 복귀 중에는 내부 지름길로 재계획하지 않는다. AGV 초기 위치 복귀까지 실행을 FINISHED로 만들지 않는다. 부품 AMR은 이 AGV 최종 복귀 대상에서 제외한다.


### 후면 AMR 부품 공급 확장 (선택 필드)

신규 정책 4 정상/수동 복구 실행은 RUN_STARTED.config에 `partsSupply: {capacity: 2, initialStock: 2}`를 포함한다. `capacity`는 1~2, `initialStock`은 0~capacity 및 maxBodies 이하 정수다. 초기 재고는 시뮬레이션 시작 조건으로 공급대에 명시적으로 배치된 키트다. 과거 실행에는 필드가 없으며 기존 동작을 유지한다.

해당 실행의 FACTORY_SNAPSHOT에는 `partsSupply` 배열이 필수다. ASM-01/02 각 한 행이며 필드는 `cellId`, `dockId`, `capacity`, `initialStock`, `available`, `inbound`, `delivered`, `consumed`, `stockoutMs`다. 후자의 수량/시간은 음이 아닌 정수다. `dockId`는 PARTS-{cellId}. `available + consumed = initialStock + delivered`, `available + inbound <= capacity`를 유지한다. inbound는 해당 공급대의 활성 PARTS 운송 수와 같고, consumed는 해당 ASM 작업을 시작한 차체 수와 같다.

부품은 실제 AMR 상하차로 공급대에 도착한 후 사용 가능하며, ASM 작업 시작 때 키트 1개를 소비한다. 소비한 키트는 복구/재시도에서 재소비하지 않는다. 재고가 없으면 차체의 직접 공정 배차를 막고 실제 보급을 기다린다. stockoutMs는 사용 가능한 부품 없이 빈 ASM으로 진입을 기다리는 차체가 있는 시간의 누적값이다.

관제 전체 스냅샷/SSE는 partsSupply를 그대로 전달한다. 과거 실행은 빈 배열을 전달한다. 현재 구현은 조립용 키트 단위이며 개별 BOM 품목·부품 창고 입고/유한 총재고는 아직 모델링하지 않는다.
