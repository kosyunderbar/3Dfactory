# v1 화면 조회·실시간 상태 계약

> 작업 ID: S00-04 · 결정일: 2026-10-05 · schemaVersion: 1  
> 설계 계약이며 REST/SSE 서버나 Vue 구현 완료를 뜻하지 않는다.

[사건 계약](events.md)의 Python 모델과 [전달 계약](delivery.md)의 두 완료 단계를 유지한다. 외부 API는 관제 서비스만 제공한다. 수집 진단은 내부 HTTP로 읽으며 DB 간 SQL 조회는 금지한다. 숫자 기본값은 [monitoring-policy.json](monitoring-policy.json), 완전한 응답은 [monitoring-examples.json](examples/monitoring-examples.json), 실제 SSE 문법 예제는 [factory-snapshot.sse](examples/factory-snapshot.sse)를 따른다. 아래에 정의한 필드는 모두 필수이며 `?`는 생략이 아니라 null 허용이다. v1에서 모르는 필드·enum·버전은 거절한다. ID·UTC 밀리초 시각·안전 정수 범위는 사건 계약과 같다.

예제의 고정 시각은 현재 실측이 아니다. buffer-lifecycle의 sourceSeq=30을 재사용하며 그 발췌 이전의 run/차체 등록·고장 사실과 알람이 이미 존재한다고 가정한다. 화면 예제는 한 시점의 조회 자료이고 statusCases는 독립 판정 사례이므로 하나의 실제 사건 스트림으로 전송하지 않는다.

## 1. 현재 상태와 이력의 경계

셀·Bay·차체·차량·활성 운송은 하나의 유효한 FACTORY_SNAPSHOT에서 가져온다. 서로 다른 sourceSeq의 배열을 조합하지 않는다. `sourceSeq`는 마지막 공장 스냅샷의 순번이며, 처리한 모든 사건의 최댓값이 아니다. `snapshotCapturedAt`은 Python capturedAt이다. 이미 처리한 검사·운송·작업 사실은 별도 이력/집계이며 오래된 스냅샷에서 새 사실을 만들어 내지 않는다.

관제 DB의 한 REPEATABLE READ 읽기 트랜잭션에서 현재 값·검사 집계·알람·최근 사건을 읽어 화면 묶음을 만든다. `viewAsOfAt`은 읽기 시작 시 서버 UTC이고 품질 구간의 끝이다. 수집 진단은 다른 서비스의 표본이므로 `sampledAt`을 따로 표시하며 같은 DB 트랜잭션의 자료라고 주장하지 않는다. 실제 상태 변경 권한은 계속 Python에 있다.

관제는 run별 화면 묶음을 500ms마다 최대 한 번 생성하고 원자적으로 게시한다. 저장/진단/시간 경과로 표시가 변하면 revision을 올린다. REST 현재 조회는 이 게시된 묶음 또는 그 부분을 반환한다. 상세 GET마다 독자적인 revision을 만들지 않는다. 없는 묶음은 503 VIEW_NOT_READY이고, 등록된 run의 초기 묶음은 WAITING으로 게시할 수 있다.

## 2. 전체 화면 DTO

| 필드 | 형식·의미 |
|---|---|
| schemaVersion | 정수 1 |
| runId, sourceId | 실행·생산자 ID |
| serverEpoch | 관제 프로세스 시작마다 발급하는 소문자 UUID v4. DB에 있던 이전 epoch를 재사용하지 않음 |
| revision | epoch 안에서 run별 1부터 증가하는 안전 정수. 넘치기 전에 새 epoch와 연결로 전환 |
| publishedAt, viewAsOfAt | 게시 직전 시각, 읽기 기준 시각. publishedAt ≥ viewAsOfAt |
| snapshotCapturedAt?, sourceSeq?, runState?, simElapsedMs? | 공장 스냅샷 없으면 모두 null. runState는 RUNNING/PAUSED/FINISHED |
| observedAfterEpoch | 이 epoch에서 시작 시 복원한 순번보다 큰 스냅샷을 실제 반영했는지. 복원만으로 true 금지 |
| dataStatus | 4절 판정값 |
| freshness | 3절의 6필드 객체 |
| delivery | 3절의 16필드 진단 객체 |
| qualityWindow | `{start,end}`. end=viewAsOfAt, start=end−300,000ms. 시작 이전 run 시간도 허용하며 그 부분은 검사 0건 |
| equipment, buffers, bodies, vehicles, activeTransports | 사건 계약 FACTORY_SNAPSHOT의 각 배열과 필드 그대로. 없으면 빈 배열이며 **0대가 확인됐다는 뜻이 아님** |
| metrics | 아래 객체 |
| alarms | 이 run의 최근 알람 100개 이하. 6절 DTO. 활성 우선, 그 안에서 occurredAt 내림차순/ alarmId 오름차순. 전체는 REST 조회 |
| recentEvents | 성공 APPLIED 사건 중 6절 event DTO 최근 50개 이하. occurredAt 내림차순/sourceSeq 내림차순/eventId 내림차순 |

metrics의 필수 필드: `currentBodyCount?`, `runningCellCount?`, `blockedCellCount?`, `downCellCount?`, `cumulativeQuality`, `windowQuality`, `alarmSummary`. 첫 네 값은 동일 물리 스냅샷 배열에서 계산하며 스냅샷 없으면 null이다. `cumulativeQuality`는 run 전체의 중복 제거한 검사, `windowQuality`는 qualityWindow의 검사다. 품질 객체는 `{inspectedCount,passCount,failCount,failRate}`이며 inspected=pass+fail, failRate=fail/inspected인 0~1 수(표시는 ×100%), 분모 0이면 null이다. `alarmSummary={activeCount,unacknowledgedActiveCount}`는 목록 제한 전 전체 집계다. 품질을 snapshot의 COMPLETED 차체 수로 계산하지 않는다. 지연 사실은 발생 구간에 들어가 값이 정정될 수 있다.

상태가 오래돼도 마지막 물리 배열/현재 수치를 보관하되 GUI에 ‘마지막 확인값’과 capturedAt을 표시한다. 품질 0건과 관측 부재를 구별한다. 데이터 지연·복원 중에는 미확정임을 표시하고 정상 상태 색이나 실시간 생산속도로 오해하게 하지 않는다.

## 3. 신선도와 수집 진단

freshness는 `{evaluatedAt,sourceAgeMs?,clockLeadMs?,state,staleAfterMs,disconnectAfterMs}`이다. evaluatedAt=viewAsOfAt, 기본 경계 3,000/10,000ms다. sourceAgeMs=max(0,evaluatedAt−capturedAt), clockLeadMs=max(0,capturedAt−evaluatedAt). 스냅샷 없으면 둘 다 null/state=NO_DATA. 종료가 확정된 실행은 state=ARCHIVED, 나머지는 age<3,000이면 FRESH, 3,000≤age<10,000이면 STALE, age≥10,000이면 EXPIRED. clockLeadMs>5,000이면 UNKNOWN이며 LIVE 금지다. 이는 단일 호스트 시계 가정의 상태 나이이지 정밀한 네트워크 지연 측정이 아니다.

수집 제공 경로: `GET /internal/v1/runs/{runId}/delivery-status`. 200은 `{protocolVersion:1,runId,sourceId,sampledAt,sourceConnected,lastReceivedAt?,lastAcceptedSeq?,nextSourceSeq,streamState,blockedSeq?,blockedCode?,pendingCount,pendingBytes,oldestPendingReceivedAt?,retryCount,rejectedCount}`. sourceConnected는 해당 run 생산자의 현재 TCP 연결 유무, lastReceivedAt은 마지막 **수락한** 사건의 최초 수신 시각, lastAcceptedSeq는 수락 순번 최댓값이다. cursor/state/중단 사유는 전달 계약의 delivery_stream을 따른다. pending은 PENDING/RETRY_WAIT/QUARANTINED 전체이며 DELIVERED 제외; pendingBytes는 LF 제외 원본 UTF-8 합, oldest는 그중 최저 receivedAt이다. 누적 retryCount는 첫 시도 이후 DB에 예약한 추가 전달 시도 수(HTTP 시작 직전 종료도 포함 가능), rejectedCount는 이미 수집에 등록된 이 run으로 식별된 TCP 영구 거절 횟수+관제에서 영구 거절된 고유 사건 수(같은 거절 재전송은 관제 수에 재가산하지 않음)다. 아직 수집에 등록되지 않은 잘못된 입력은 제한 진단 로그로 남기며 정상 전달 행을 만들지 않는다. 시도 횟수는 실제 네트워크 발송 확정 계측이 아니며 명시적 재개에도 누적값을 유지한다. sourceConnected는 현재 열린 TCP 연결에서 해당 run의 수집 성공을 확인한 표본이며 과거 DB 행/ACK만으로 true를 추정하지 않는다. 미확인 run은 404, 읽기 실패는 503이다. JSON 상한 8KiB. 내부 주소는 브라우저에 제공하지 않는다.

관제는 구독/조회 중인 run의 진단을 1초마다 조회(동일 run 요청 합치기)하며 HTTP 연결/전체 응답 제한 각각 500/1,000ms이다. 실패는 오래된 캐시로 숨기지 않는다. 화면 delivery는 위 응답에서 protocolVersion을 제외한 15필드에 `diagnosticState`를 더한 **16필드**다. diagnosticState=AVAILABLE/UNAVAILABLE. runId/sourceId는 화면과 같아야 하며 잘못된 버전·ID·시각·응답은 실패다. 실패 시 마지막 성공 진단값은 남겨도 UNAVAILABLE이다. 한 번도 성공하지 않았으면 run/source만 알려진 값, sampledAt과 나머지 12 값은 null이다. 성공 표본도 나이가 ≥3,000ms이면 UNAVAILABLE; sampledAt이 서버보다 >5,000ms 앞서면 동일하다. UNKNOWN 화면에서 이전 수치는 ‘마지막 진단’이다.

`oldestPendingAgeMs=max(0,viewAsOfAt−oldestPendingReceivedAt)`는 화면 판정용 파생값이며 DTO 추가 필드가 아니다. pendingCount>0일 때 oldest는 필수, 0이면 null. pendingCount≤5,000, pendingBytes≤128MiB. streamState의 BLOCKED는 영구 거절, PAUSED_*는 재시도·의존·설정·순번 대기 중단이다. `pendingCount`는 차체 Bay의 W/R과 관계없는 **보고서 대기**다.

## 4. dataStatus 판정 순서

아래에서 처음 맞는 한 가지를 사용한다. 종료 확정은 RUN_FINISHED 사실이 관제에 커밋되고, AVAILABLE 진단의 pendingCount=0, nextSourceSeq>그 종료 사건 sourceSeq임을 뜻한다. runState 필드는 물리 스냅샷 값이므로 종료 사실만 먼저 오면 이전 RUNNING/PAUSED가 남을 수 있다. FINISHED 표시는 종료 사실 기준이며 새 물리 최종값을 추정하지 않는다.

| 순서 | 조건 | dataStatus / 화면 의미 |
|---|---|---|
| 1 | 관제 처리 상태 BLOCKED 또는 알려진 진단 streamState=BLOCKED/PAUSED_* | BLOCKED / 처리 중단과 순번·코드 표시. 오래된 진단이면 그 사실도 표시 |
| 2 | 종료 확정 | FINISHED / 보관된 최종 확인값, 연결 끊김 알람을 새로 만들지 않음 |
| 3 | 공장 스냅샷 없음 | WAITING / 아직 공장 상태 없음. 진단 실패도 함께 표시 |
| 4 | observedAfterEpoch=false | RESTORING / 저장 상태 복원, 새 보고 전 |
| 5 | diagnosticState≠AVAILABLE 또는 freshness=UNKNOWN | UNKNOWN / 전달 상태·시계 확인 불가 |
| 6 | sourceConnected=false 또는 freshness=EXPIRED | DISCONNECTED / 연결 끊김 또는 10초간 상태 보고 없음 |
| 7 | freshness=STALE | STALE / 3초 이상 오래된 공장 상태 |
| 8 | pendingCount>0 이고 oldestPendingAgeMs≥1,000, 또는 streamState=RETRY_WAIT/GAP_WAIT | CATCHING_UP / 업무 반영을 따라잡는 중 |
| 9 | runState=PAUSED | PAUSED / 의도적 공장 일시정지, 상태 보고는 계속 가능 |
| 10 | 그 외 | LIVE / 최근 관측이며 전달이 정한 1초 예산 안에 있음 |

짧은 정상 전달 대기가 있다고 LIVE를 숨기지는 않되 pending 수와 표본 시각을 항상 조회할 수 있어야 한다. LIVE는 ‘모든 최신 사건 처리가 0ms에 완료’라는 보증이 아니다. TCP 정상, ACK 성공, SSE onopen만으로 LIVE를 정하지 않는다. BLOCKED라도 physical slots를 해제하지 않는다. 상태가 겹치면 freshness/delivery의 개별값도 표시한다.

브라우저의 SSE 연결 상태는 별도 `CONNECTING/OPEN/RECONNECTING/CLOSED` 표시로 관리한다(서버 DTO 필드 아님). 마지막 유효 전체 묶음 이후 3초면 ‘화면 수신 지연’, 10초면 ‘화면 연결 확인 필요’로 LIVE 표시/보간을 중지한다. 서버 dataStatus를 임의로 덮어 저장하지 않는다. 한 번 더 받은 오래된 묶음이나 heartbeat는 이 타이머를 초기화하지 않는다. 수신된 sourceAgeMs에 브라우저 단조 시계로 잰 수신 후 경과를 더한 표시 나이도 3초 경계를 넘으면 정상 표시/보간을 중지한다(ARCHIVED 제외). 이 값은 화면 보조 판단이며 서버 DTO나 물리 좌표를 수정하지 않는다. PAUSED/STALE 등에서는 이동 애니메이션을 멈추고 받은 좌표만 보인다.

## 5. REST 경로·응답

JSON Content-Type=application/json, Cache-Control=no-store. 모두 관제 제공. SQL 오류·내부 주소를 응답에 넣지 않는다. 오류는 `{schemaVersion:1,code,message,requestId}`(UUID v4), 400 INVALID_QUERY/INVALID_BODY, 404 RUN_NOT_FOUND/RESOURCE_NOT_FOUND, 409 CURSOR_MISMATCH/CURSOR_EXPIRED, 503 VIEW_NOT_READY/DB_UNAVAILABLE이다. 알람 확인 요청 몸체는 최대1KiB, 외부 오류 응답은 최대8KiB다. 크기 초과 413 PAYLOAD_TOO_LARGE, 잘못된 media type 415 UNSUPPORTED_MEDIA_TYPE. 명시하지 않은 쿼리는 400이다.

| 경로 (GET 기본) | 응답·조건 |
|---|---|
| /api/v1/factory/layout?runId=… | 필수 runId. `{schemaVersion,runId,sourceId,config}`; config는 RUN_STARTED.config 그대로, 실행 중 불변 |
| /api/v1/runs | 6절 페이지. item=`{runId,sourceId,startedAt,finishedAt?,processingState}`. state=ACTIVE/BLOCKED. startedAt 내림차순/runId 내림차순. limit/cursor만 허용 |
| /api/v1/runs/{runId}/snapshot | 2절 전체 DTO |
| …/equipment/{equipmentId}, …/buffers/{bufferId}, …/vehicles/{vehicleId} | 공통 현재 봉투+`data`에 해당 snapshot 요소 한 개. 등록됐지만 snapshot 없으면 data=null |
| …/bodies/{bodyId}, …/tags/{tagId}/body | 같은 봉투+`data`에 body 요소. 태그는 해당 run의 1:1 등록을 통해 bodyId로 찾음. 등록됐지만 관측 안 된 차체도 data=null |
| …/events | 6절 event 페이지; from/to/cellId/equipmentId/bodyId/vehicleId/eventType/limit/cursor |
| …/quality | from/to; `{schemaVersion,runId,viewAsOfAt,window:{start,end},quality,delivery}`; quality는 2절 4필드 |
| …/trends | from/to/bucketMs; `{schemaVersion,runId,viewAsOfAt,window,bucketMs,buckets,delivery}`. 6절 버킷 |
| …/alarms | from/to/conditionActive/acknowledged/severity/limit/cursor; 6절 alarm 페이지 |
| /api/v1/system/status?runId=… | 필수 runId. 공통 현재 봉투+`data={operationsState,delivery}`. operationsState=ACTIVE/BLOCKED |
| POST /api/v1/alarms/{alarmId}/acknowledge | `{operatorId}` ASCII `[a-zA-Z0-9_-]{1,64}`. 200=`{schemaVersion,runId,viewAsOfAt,alarm}`; alarm은 6절 DTO |
| …/stream | 7절 SSE |

공통 현재 봉투는 전체 DTO 중 `schemaVersion,runId,sourceId,serverEpoch,revision,publishedAt,viewAsOfAt,snapshotCapturedAt,sourceSeq,runState,simElapsedMs,observedAfterEpoch,dataStatus,freshness,delivery`의 **15필드**다. detail은 여기에 data를 붙인다. 지도와 상세를 동시에 보일 때 현재 값은 최신 전체 묶음의 요소를 우선한다. 등록된 ID와 관측 부재(null)를 없는 ID(404)와 구별한다. 이력은 최신 현재 값으로 덮지 않는다.

알람 확인은 관제 DB에 최초 acknowledgedAt/acknowledgedBy를 원자적으로 기록한다. 재요청은 최초 값을 그대로 200 반환(다른 operator도 최초 값을 보존). POST 응답을 지도 현재 묶음에 직접 합치지 않고 다음 게시 revision에서 확인 표시를 갱신한다. conditionActive/resolvedAt·Python 상태·예약에는 영향을 주지 않는다. 복구된 알람도 확인 가능하다. operatorId는 학습용 입력 이름이며 인증된 사용자 신원을 보증하지 않는다. notes는 P1로 API/DTO 구현을 이번 P0 계약에 넣지 않는다.

## 6. 기간·이력·품질

from/to는 UTC 밀리초이며 `[from,to)` 반열린 구간이다. 둘 다 생략하면 `[viewAsOfAt−5분,viewAsOfAt)`, 한쪽만 지정하면 400. from<to, 최대 24시간, to≤viewAsOfAt. 필터 ID는 사건 규격, eventType은 17종, severity는 INFO/WARNING/CRITICAL, boolean은 true/false만. 알람 기간은 occurredAt 기준이다. 검사 품질은 inspection occurredAt 기준이다.

페이지는 `{schemaVersion,runId?,viewAsOfAt,items,nextCursor?}` 5필드이며 runs만 runId=null이다. limit 기본50/최대200/최소1. 페이지 JSON은 최대512KiB이며 완전한 item 단위로 상한 전에 멈추고 마지막 포함 item의 nextCursor를 제공한다. 따라서 요청 limit보다 적은 결과와 non-null cursor가 함께 올 수 있다. 단일 item도 상한에 못 들어가면 503 VIEW_NOT_READY이며 필드를 잘라 보내지 않는다. 첫 페이지는 해당 조회 자료의 현재 최대 커밋 recordOrdinal을 fence로 고정한다. 이 번호는 event_projection/알람/run 등록의 각 소유 쓰기 경계에서 잠금 아래 증가시키고 커밋 순서를 보장하는 내부 번호이며 Python sourceSeq와 다르다. 번호를 얻고 늦게 커밋한 행이 이미 발급한 fence 안으로 들어오지 않도록 한다. 실제 컬럼/제약은 S01/S05에서 구현한다. cursor는 schemaVersion/runId/정규화한 필터/limit/fence/정렬 마지막 키/첫 viewAsOfAt/만료시각을 서버가 변조 검출 가능하게 인코딩한 불투명 토큰(최대2KiB)이다. 다음 페이지는 cursor와 동일 필터·limit만 허용, 첫 viewAsOfAt 유지, 10분 후 409 CURSOR_EXPIRED. 첫 조회 이후 들어온 지연 사실은 fence 밖이므로 새 조회에서 보인다. 삭제/보존 정책 변경으로 fence를 보장 못하면 409. 페이지 사이 알람 확인/복구는 바뀔 수 있으며 정렬/포함 조건은 첫 viewAsOfAt 시점의 occurred/resolved/ack 시각으로 평가한다. 알람 item도 첫 viewAsOfAt보다 늦은 resolvedAt/acknowledgedAt을 null로 표현하여 해당 시점의 conditionActive를 계산한다. 조회 기간 fence는 과거 사실을 영원히 누락시키는 정책이 아니다.

event DTO의 10필드: `{eventId,sourceSeq,eventType,occurredAt,receivedAt,appliedAt,cellId?,bodyId?,vehicleId?,payload}`. payload는 원래 유효 사건 payload; 조회 범위 run/source는 봉투에 해당한다. 성공 사실만 제공하고 거절 원문은 화면 이력에 섞지 않는다. cellId는 payload.cellId 또는 equipmentId가 대응하는 셀; BUFFER 사건은 buffer→cell; TRANSPORT 사건은 CELL/BUFFER 목적지 셀 우선, 없으면 출발 셀; BODY_REGISTERED는 초기 위치가 CELL/BUFFER면 그 셀; 나머지 없으면 null. bodyId는 payload.bodyId 또는 unitId, vehicleId는 payload.vehicleId, snapshot 등 여러 개체를 담은 사건은 이 세 인덱스를 null로 두며 필터는 직접 인덱스 일치만 한다. equipmentId 필터는 그 셀의 cellId에 매핑한다. 날짜 정렬 동률은 sourceSeq/eventId로 확정한다.

alarm DTO의 11필드: `{alarmId,runId,type,severity,targetId,occurredAt,conditionActive,resolvedAt?,acknowledgedAt?,acknowledgedBy?,message}`. ID는 UUID v4, type=EQUIPMENT_DOWN/BUFFER_FULL/SOURCE_STALE/SOURCE_DISCONNECTED/PROCESSING_BLOCKED/QUALITY_WARNING. 대상은 cell/buffer/source/run ID. 정상 복구 시 resolvedAt과 conditionActive=false를 함께 기록; conditionActive=true이면 resolvedAt=null, false이면 resolvedAt은 필수다. acknowledgedAt/acknowledgedBy는 둘 다 null 또는 둘 다 값이어야 한다. occurrence는 조건의 false→true 전환마다 새 ID이고 매 주기 중복 생성하지 않는다. severity 기본값은 EQUIPMENT_DOWN/SOURCE_DISCONNECTED/PROCESSING_BLOCKED=CRITICAL, BUFFER_FULL/SOURCE_STALE/QUALITY_WARNING=WARNING이다. 고장·만석은 검증된 스냅샷에서 조건을 판정하고 오래된 값이나 진단 실패만으로 복구시키지 않는다. SOURCE_STALE은 진행 실행의 STALE/EXPIRED, SOURCE_DISCONNECTED는 진행 실행의 sourceConnected=false 또는 EXPIRED, PROCESSING_BLOCKED는 4절 첫 조건이며 해당 진단/업무 상태로 복구를 확인한다. 종료 확정 시 소스 알람은 해소하고, WAITING/RESTORING/UNKNOWN만으로 고장 사실을 만들지 않는다. 초기 P0는 EQUIPMENT_DOWN/BUFFER_FULL/SOURCE_STALE/SOURCE_DISCONNECTED/PROCESSING_BLOCKED; QUALITY_WARNING 생성은 P1이며 조회 enum만 미리 호환한다. 조건과 무관한 수치 추정으로 정상 복구시키지 않는다.

trends bucketMs는 1,000/5,000/60,000만 허용, 버킷 최대300. UTC epoch의 bucket 경계에 맞추고 요청 구간과 교차한 구간만 집계; bucket=`{start,end,quality}`. 첫/끝은 from/to로 잘라 반열린 구간을 유지한다. 빈 버킷은 inspected/pass/fail=0, failRate=null. 데이터 부재를 뜻하는 물리 수치를 0으로 삽입하지 않는다. P0 trends는 검사 추이만 제공하고 시간 적분 가동률은 S09 이후 별도 정의한다.

## 7. SSE 프레임·수신 순서·상한

HTTP 200, Content-Type=text/event-stream, UTF-8, Cache-Control=no-store, proxy buffering 비활성. frame은 `id: {serverEpoch}:{revision}\nevent: factory-snapshot\ndata: {한 줄 전체 JSON}\n\n`이다. JSON 문자열 안 개행은 이스케이프한다. 연결마다 즉시 최신 전체 묶음(없으면 WAITING 생성)을 보내고 이후 최대2회/초. EventSource는 이름 있는 이벤트를 addEventListener('factory-snapshot', …)로 받는다. 표준은 [WHATWG SSE 규격](https://html.spec.whatwg.org/multipage/server-sent-events.html)을 따른다. `retry: 2000`을 연결 첫머리에 보낼 수 있다. 예제 파일 끝의 빈 줄도 필수다.

Last-Event-ID를 받아도 누락된 과거 화면을 재생하지 않고 최신 전체 묶음을 보낸다. 이력 조회는 REST를 사용한다. heartbeat는 5초마다 `: heartbeat\n\n`이며 물리 관측/유효 전체 묶음이 아니다. 종료 실행은 보관값을 첫 전송하고 변경 없는 동안 heartbeat만 보내도 된다. FINISHED 화면도 브라우저 연결 표시는 별도로 유지한다.

브라우저는 연결/실행 선택마다 로컬 generation을 증가시키고 이전 EventSource를 close하며 이전 REST는 abort 또는 generation 불일치로 폐기한다. 새 연결의 첫 유효 전체 묶음만 epoch 비교 기준을 설정한다. 같은 연결의 epoch 변경은 재연결 대상으로 처리한다. 재연결 첫 묶음도 epoch가 같으면 기존 revision 기준을 유지한다. 같은 run/epoch에서 revision≤적용값인 응답은 버리고, 더 큰 revision이어도 sourceSeq가 감소하면 프로토콜 오류로 재조회한다. 이 검사에서 null→관측 순번은 허용, 관측 순번→null은 같은 epoch에서 금지한다. 옛 epoch의 늦은 REST 응답은 새 epoch를 되돌릴 수 없다. 이 규칙으로 동일 sourceSeq에서 알람/품질/신선도만 변경된 새 revision은 적용할 수 있다.

SSE/전체 REST JSON은 UTF-8 최대512KiB. 초과하면 몸체/슬롯을 잘라 정상으로 보내지 않고 503 VIEW_NOT_READY 및 서버 진단을 남긴다. 첫 묶음 생성에 실패하거나 503/429로 스트림을 시작하지 못하면 유효 factory-snapshot을 보내지 않는다. 연결당 전송 중 1개와 대기 최신 묶음 1개만 보관, 낡은 미전송 묶음은 교체. 쓰기 제한5초, 최대 SSE연결20, 초과는 429 STREAM_LIMIT/Retry-After:2(REST 오류 봉투). 종료·오류·타임아웃 시 대기 자료/구독자 제거. 브라우저 기본 EventSource 재연결을 사용하되 terminal error나 10초 유효 묶음 부재 시 close 후 2초 간격 재생성, 동시에 연결/재연결 타이머는 하나만 허용한다. 실제 전송 크기·메모리·복구는 S06/S08/S09에서 검증한다.

## 8. 검증 범위

S00-04 당시에는 문서·예제·경계 판정만 확인했다. S04-01~04에서 SSE를 제외한 관제 사건 반영·REST 조회/SQL·신선도/알람을 구현했고 실제 PostgreSQL/HTTP를 확인했다. S05에서 자동 전달/수집 진단 제공·재시작 복구를 구현했고 실제 두 DB/TCP/HTTP 및 Compose 연결에서 REST LIVE→FINISHED를 확인했다. S06에서 비차단 SSE·같은 전체 묶음의 실제 최소 Vue 셀/태그 연결을 구현하고 두 DB/프록시 SSE/Chrome에서 검증했다. 전체 SVG 지도·이력/차트/알람 UI는 S07에서 완료했다. 실제 명령과 결과는 [관제 실행 안내](../../services/operations-service/README.md)와 [공유 검증 안내](<../../docs/validation/최소 검증 시나리오와 도구.md>)를 따른다. 문서 자료 검사 명령은 `python3 scripts/check_monitoring_examples.py`이며 [최소 검증 시나리오와 도구](<../../docs/validation/최소 검증 시나리오와 도구.md>)에 이후 구현에서 필요한 증거를 구분했다. 통신·DB·브라우저 검증을 예제 통과로 대체하지 않는다. 구체적 실행 패키지/이미지 버전은 S01 실행 기반 작업에서 고정한다.


S06 구현은 정확한 stream 경로를 Servlet 비동기 필터로 처리하며 나머지 REST는 기존 MVC 조회를 유지한다. 브라우저는 첫 유효 SSE로 연결 epoch를 정하고 그 이전의 REST 결과를 적용하지 않는다. 셀/버퍼와 차체 상세는 같은 전체 묶음을 사용하며 이력과 물리 제어를 맡지 않는다. schemaVersion=1/DTO/정책 파일은 변경하지 않았다. 제한된 채널의 대기 교체/5초 자원 회수와 실제20개 연결 한도는 확인했으나 실제 저속 네트워크·대규모 메모리/성능은 S08/S09 범위다.


## S07 구현 상태와 조회 경계

S07-01~04에서 실제 SVG 셀/차량/Bay 지도·태그 검색/대상별 상세·관련 이력·품질 ECharts·알람 확인/복구 관측·사건/알람 기록과 모바일/키보드 접근을 연결했다. schemaVersion=1/DTO/기존 API 경로와 서버 물리 제어 책임은 유지한다. 이력은 처음 정한 from/to와 cursor 기준으로20건씩 최대100건 표시하며 SSE마다 재조회하지 않는다. Bay 관련 이력은 기존 API의 연결된 cellId 범위다. quality/trends는 동일 UTC 구간으로 함께 읽고 부분 응답은 표시하지 않는다. 요청은5초 제한·실행/epoch/필터/채널 순서로 늦은 결과를 배제한다. 확인 POST의 성공 답장은 물리 상태를 덮지 않고 다음 SSE가 확인 정보를 표시한다. [실제 Vue 안내](../../services/factory-console/README.md) · [실제 검증](<../../docs/validation/최소 검증 시나리오와 도구.md>).
