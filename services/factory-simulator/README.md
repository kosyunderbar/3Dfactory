# Python 공장 시뮬레이터 실행 기반

> S01-04 · Python 3.12 · 제삼자 패키지 없음 · S02 전체 공장 모델·취소/장애·부품 AMR·v1 사건/전체 스냅샷 완료; S03 송신/ACK/제한 재전송 완료; 일반 기동의 실시간 생산 자동 구동은 후속

이 프로그램은 셀·차체·태그·차량·버퍼 예약의 물리 상태를 결정한다. 현재는 설정 검사, run·차체/태그·단일 위치, 셀 작업/검사·예약·운송·취소/장애·부품 AMR와 로컬 v1 보고, 종료 신호 처리와 실행 상태 확인이 있다. 기동 로그의 `MODEL_INITIALIZED`는 공장 운전 시작이 아니다. 일반 기동은 TCP 송신을 자동 시작하지 않는다. --send-events와 SourceSession으로 명시적인 송신을 지원한다. 차체 등록은 명시적인 --initial-bodies 옵션으로 확인할 수 있다.

프로젝트 루트에서 Python 3.12를 사용한다.

```sh
scripts/simulator.sh setup
scripts/simulator.sh test
INGESTION_TCP_HOST=127.0.0.1 INGESTION_TCP_PORT=9090 scripts/simulator.sh run --check-config
INGESTION_TCP_HOST=127.0.0.1 INGESTION_TCP_PORT=9090 scripts/simulator.sh run
```

`setup`은 `.build-cache/simulator-venv/`에 격리 환경을 만들며 pip 다운로드도 필요 없다. `test`는 현재 24개의 unittest로 설정·등록·단일 위치·작업·검사·배차·운송·시나리오·송신을 확인한다. 정상 생산 1대/3대와 귀환 중 현재 위치에서 재배차하는 사례를 포함한다. 일반 실행은 Ctrl+C로 종료한다. 환경 변수 예시는 [.env.example](../../.env.example)에 있다. 명령의 host/port는 수집 TCP 연결 대상이다. 실제 송신은 해당 주소에 일반 수집 서비스가 기동해야 한다.

Docker Compose에서는 환경 변수를 자동으로 전달한다. 컨테이너의 heartbeat 검사는 Python 프로세스의 기본 루프가 살아 있는지만 확인한다. 업무 정합성·네트워크 수집 상태와 별개다. 가상환경 없이 직접 실행하려면 이 디렉토리에서 `python3 -m factory_simulator`를 사용한다.

[작업 8 설명](<../../docs/work-notes/작업 8. Python과 Vue 기본 앱.md>) · [전체 실행 안내](../../infrastructure/README.md)

## S02-01 공장 모델 확인

공장 실행 설정과 차체/태그 등록·단일 위치 소유의 기초 모델을 구현했다. 기본 구성은 `factory_simulator/config/default-run.json`이며 seed/sourceId/config를 갖는다. 공장 배치 값은 v1 사건 계약을 따르고 실행 동안 고정된다. 기본 모델은 빈 등록부로 초기화하며 일반 실행에서 작업·운송을 자동 진행하지 않는다. 일반 기동 로그는 `MODEL_INITIALIZED`, factoryRunStarted=false다.

```sh
# TCP 대상/서버 없이 차체 3대를 BODY-IN에 등록해 로컬 설명 출력
scripts/simulator.sh run --inspect-model --initial-bodies 3
# 복사해 수정한 실행 설정 적용; 경로는 절대 경로 권장
scripts/simulator.sh run --inspect-model --config /absolute/path/run.json --initial-bodies 3
```

새 runId는 UTC 날짜와 UUID v4이며 차체와 태그는 run 안에서 1:1 고정된다. maxBodies는 완료/반출 기록까지 포함한 등록 상한이다. 초기 배치 fixture 모드는 모델 생성과 명시적인 --demo-work/--demo-dispatch/--demo-transport에서만 허용하며 일반 기동/--inspect-model에는 켜지지 않는다.

직접 위치 변경 기초 함수는 이제 명시적 시험 배치 전용이다. 일반 모델에서는 거절하고, 배차된 차체도 이 함수로 이동할 수 없다. 셀 작업 시작은 다음 공정·차체 상태·점유·일시정지 조건을 별도로 검사한다. 입력 명령을 한 모델 소유 스레드에서 처리한다. `inspect-model` 출력은 로컬 미리보기이며 사건/SSE/full snapshot이 아니다.

[작업 10 설명](<../../docs/work-notes/작업 10. 공장 설정과 차체·태그 등록.md>)에서 설정·가상 이름표·단일 위치의 의미와 최소 검증을 설명한다. S02-01 당시의 결과 기록이다. 현재 S03까지 완료했으며 다음은 S04-01이다. 네트워크/업무 기능이 구현되기 전까지 서버 준비 상태를 제조 데이터 LIVE로 사용하지 않는다.

## S02-02 셀 작업·최종 검사

```sh
scripts/simulator.sh run --demo-work
```

차체 한 대의 세 공정 작업을 명시적인 시험 배치로 확인한다. 4/6/3초의 작업 기록, 검사 1건(PASS), 완료 이력과 QC 셀 안의 차체를 출력한다. `demoFixture=true`, `transportImplemented=false`, `handoffs=TEST_FIXTURE_ONLY`로 실제 배차/AGV 운송과 구분한다. 자동 실행 시간이 아니라 tick을 직접 진행한 결과다. --initial-bodies와 동시 사용하지 않는다.

Python의 `start_work(cell_id)`, `tick()` / `advance(delta_ms)`, `pause()` / `resume()`로 모델을 제어한다. advance는 설정 tick의 양의 정수 배수만 받는다. 작업 시간은 활성 tick만 세고 UTC 기록 시각과 구분한다. 조립 완료는 WAITING_UNLOAD, QC 완료는 COMPLETED이며 차체는 셀 안에 남는다. 셀은 BLOCKED / WAITING_PICKUP으로 보유를 유지한다. 여기서 WAITING_PICKUP은 로컬 대기 표시이며 배차가 승인됐다는 뜻이 아니다. S02-03에서 BUFFER_FULL/NO_VEHICLE 판단과 배차를 추가했다.

검사는 기본 seed/failProbability를 사용한다. 모델 생성의 `quality_results=('PASS', 'FAIL')`는 시험용 순환 배열이다. 검사 전 결과는 NOT_INSPECTED/시각 null이고 완료 시 inspectionId와 결과를 한 번 만든다. FAIL의 defectCode는 SIM_DEFECT_01이다. COMPLETED는 최종 검사 완료이며 GOOD/HOLD 도착과 별개다.

시험 배치의 선행 completed_cell_ids는 배치할 셀 앞의 정확한 공정 순서여야 한다. 시험용 IDLE 셀에 아직 작업을 시작하지 않은 차체가 있으면 로컬 출력에 fixturePendingStart=true를 표시한다. 이는 완전한 v1 스냅샷이 아니다. 일반 실행은 여전히 MODEL_INITIALIZED와 heartbeat만 유지한다. 작업 fact를 네트워크 사건으로 보내거나 실제 Vue에 연결하지 않는다.

[작업 11 설명](<../../docs/work-notes/작업 11. 셀 작업과 최종 검사.md>) · S02-02 당시의 결과 기록.

## S02-03 슬롯/AGV 동시 배차

```sh
scripts/simulator.sh run --demo-dispatch
```

`assign_transport(body_id)`는 INPUT의 신규 차체 또는 작업을 마친 BLOCKED 셀의 차체만 받는다. 다음 공정의 Bay와 설정 경로를 선택하고, 빈 슬롯과 빈 차체 AGV(IDLE 또는 RETURNING)를 모두 확보한 뒤 ASSIGNED 운송을 만든다. 슬롯/운송/차체/AGV 참조와 번호를 한 소유 스레드에서 함께 갱신한다. AMR은 차체 배차 대상이 아니다. 마지막 QC는 PASS→GOOD, FAIL→HOLD이며 예약/slotId는 null이다.

`buffer(buffer_id)`는 슬롯별 OCCUPIED/RESERVED/FREE를 실제 차체 위치와 활성 운송에서 계산한다. W+R≥C이면 BUFFER_FULL을 반환한다. 슬롯이 있어도 AGV가 없으면 NO_VEHICLE이고 예약을 만들지 않는다. 성공 또는 동일 차체의 반복 요청은 approved=true / WAITING_PICKUP과 동일 transportId를 반환한다. 잘못된 출발 상태/공정·일시정지 요청은 ModelError로 거절한다.

승인해도 차체 위치와 WAITING_UNLOAD/COMPLETED 상태를 유지한다. AGV는 TO_PICKUP, 실제 적재 bodyId는 null이다. R은 ASSIGNED부터 포함하고 시간 경과/일시정지만으로 만료시키지 않는다. S02-03 당시에는 픽업/출발/도착/반환/취소 동작이 없었다. 현재 모델 운송 수명은 아래 S02-04를 따른다. 취소는 아래 S02-05에서 구현했다. 재평가되는 blockedReason은 새 배차를 자동 수행하지 않는다.

새 데모는 만석 목적지의 완료 차체를 셀에 보유한 거절 결과, 시험용 자리 제거 뒤 배차 결과, 별도 run에서 마지막 슬롯의 두 요청을 출력한다. fixtureRemoval=TEST_ARRANGEMENT_ONLY이며 제거를 실제 셀 진입/슬롯 반환으로 해석하지 않는다. 기본 설정에서 C=3/W=2/R=1/A=0을 확인한다. maxBodies는 ASM-01/02의 최대 Bay 용량+1 이상이어야 하며 --initial-bodies와 함께 사용할 수 없다.

inspect 출력에 buffers/vehicles/activeTransports와 차체의 활성 운송/예약 참조를 추가했다. 여전히 로컬 확인 JSON이며 완전한 FACTORY_SNAPSHOT/네트워크 사건이 아니다. 일반 기동은 MODEL_INITIALIZED와 heartbeat를 유지한다.

[작업 12 설명](<../../docs/work-notes/작업 12. 슬롯 예약과 AGV 배차.md>) · S02-03 당시의 결과 기록.

## S02-04 운송 수명·셀 진입·슬롯 반환

```sh
scripts/simulator.sh run --demo-transport
```

`start_transport(transport_id)`는 승인된 AGV의 픽업 이동을 시작한다. tick에서 TO_PICKUP→LOADING→MOVING→UNLOADING→RETURNING→IDLE을 진행한다. LOADING 완료 때만 차체를 출발지에서 AGV로 옮기고 transport를 IN_TRANSIT으로 바꾼다. UNLOADING 완료 때 Bay의 예약을 실제 점유로 바꾸거나 GOOD/HOLD에 인계하고 transport를 COMPLETED로 기록한다. 차량은 비워진 뒤 새 배차가 있으면 현재 위치에서 다음 픽업으로 이동한다. 배차할 작업이 없을 때는 RETURNING으로 시작점에 복귀한다. 귀환 중인 빈 AGV도 배차 대상이며, 픽업 지점과의 직선 거리가 가장 가까운 차량을 선택하고 동률이면 vehicleId 순서를 사용한다. 슬롯 점유에는 완료 운송/예약의 이력 ID를 보존한다.

`enter_cell(body_id)`는 다음 셀의 Bay에 대기하는 차체를 빈 IDLE 셀로 인계하면서 작업 시작과 슬롯 반환을 함께 처리한다. CellEntry 로컬 기록에는 슬롯/선행 운송/새 작업 ID와 반환 직후 availableSlotsAfterRelease를 남긴다. 곧바로 재배차하므로 최종 조회의 A는 다시 0일 수 있다. Bay 도착과 셀 진입은 별도 동작이다.

`redispatch()`는 완료된 후공정 셀부터 검사하고 신규 INPUT을 이어 검사하며 가용 슬롯/AGV만큼 배차하고 이동을 시작한다. 운송 흐름을 활성화하면 각 tick 끝과 셀 진입 직후 재배차한다. Bay→셀 진입 자체는 명시적으로 호출한다. `assign_transport()`만 호출한 S02-03 배차 확인은 이동을 자동 시작하지 않는다. 일반 서비스 기동도 아직 heartbeat 루프다.

적재 운반은 구성 경로의 점들을 거리 비율로 보간하고 travelDurationMs를 사용한다. 빈 픽업/귀환은 해당 경로의 거리/시간에서 얻은 속도로 직선 이동하며 tick 단위로 올림한다. 위치가 같아도 한 tick을 사용한다. 적재/인계 대기는 각각 한 tick으로 단순화한다. 동선 충돌 제어·실제 기구 동작은 구현하지 않는다. 일시정지에서는 작업·차량 위치·인계·재배차를 진행하지 않는다.

모델 tick과 셀 진입/재배차는 전환 중 오류가 나면 그 전환의 소유/작업/예약/차량/번호를 복구한다. 여러 tick의 advance는 앞서 성공한 tick까지 취소하는 전체 일괄 트랜잭션은 아니다.

데모는 일반 등록 차체 한 대의 세 작업/한 검사/네 운송/세 셀 진입과 GOOD 도착·귀환, 별도 초기 배치의 만석 예약 수명을 출력한다. 초기 배치 이후의 픽업/인계/슬롯 반환은 모델 동작이며 fixture 위치 변경으로 대신하지 않는다. maxBodies는 ASM-02 Bay 용량+1 이상이어야 한다. 길게 수정한 설정은 5000 tick 확인 한도에서 오류가 날 수 있다.

inspect에는 전체 운송 기록, 셀 진입/반환 기록과 차량의 남은 구간 시간을 추가했다. inspect는 로컬 진단이며 v1 사건/전체 스냅샷과 구분한다. 아래 S02-05의 snapshot/events를 사용한다. [작업 13 설명](<../../docs/work-notes/작업 13. AGV 운송과 버퍼 슬롯 반환.md>) · S02-04 당시의 결과 기록.

## S02-05 취소·장애·부품 AMR·v1 보고

```sh
scripts/simulator.sh run --demo-scenarios
```

`cancel_transport(id)`는 BODY/ASSIGNED이고 차체가 출발지에 있을 때만 예약/차량을 함께 반환한다. TO_PICKUP/LOADING에서 가능하고 IN_TRANSIT 이후는 거절한다. 반복 취소는 이전 결과를 반환하며 새 배정을 건드리지 않는다. 취소된 차체만 자동 재배차를 보류하고 명시적 assign_transport 재시도로 새 번호를 받는다. `complete_transport(id)`도 완료 후 반복 요청에 기존 결과만 반환하며 인계 전 호출은 거절한다.

`assign_parts('ASM-01'|'ASM-02')`는 IDLE AMR과 kit 번호로 STORE→PARTS_DOCK 운송을 만든다. bodyId/예약/slotId는 null이다. start_transport로 운송하고 parts 조회로 실제 키트 위치를 확인한다. 차체/태그/Bay 카운터와 분리하며 조립의 재고 조건에 연결하지 않는다. 키트 등록 상한은 maxBodies×2다. v1의 취소는 BODY만 지원한다.

`fail_cell`은 DOWN/resumeState로 차체/작업 번호/남은 시간을 보존한다. source DOWN이면 적재 완료를 보류하고 target DOWN이어도 예약한 Bay 도착은 가능하다. enter_cell은 복구 전까지 거절한다. recover_cell 후 같은 작업을 이어 간다. `delay_transport(id, milliseconds)`는 ASSIGNED의 적재 운반 시간에 누적 지연을 넣고 `set_quality_pattern(('FAIL','PASS'))`는 이후 검사 배열을 시작한다. 고장/복구·품질·지연은 명시적 SCENARIO_CHANGED로 기록한다.

`events`는 변경 불가능한 Event 튜플이고 to_dict는 읽기 사본, ndjson은 재사용 가능한 동일 봉투/LF 바이트의 문자열이다. 첫 사건은 RUN_STARTED이고 새로운 사실에만 sourceSeq/UUID를 부여한다. 작업·검사·슬롯·인계·운송·실행/시나리오 전환을 기록하고 실패 시 상태와 사건을 함께 되돌린다. 모델은 TELEMETRY_UPDATED를 별도로 발행하지 않는다. 저널은 메모리이며 S03의 SourceSession 송신 경로에서는 확인된 원본을 해제하고 순번을 별도로 유지한다. Python 프로세스 자체의 영속 복원은 P0 범위 밖이다.

`snapshot()`은 계약의 전체 payload, `publish_snapshot()`은 그 상태의 FACTORY_SNAPSHOT 사건을 생성한다. fixture의 IDLE 셀에 아직 시작하지 않은 차체가 있으면 완전한 보고를 거절한다. inspect의 진단 필드나 이력 배열을 v1 payload에 넣지 않는다. 일반 모델의 스냅샷은 명시적 호출이다. S06의 --connected-demo는500ms 기본 보고와 실제 시간 구동을 연결한다. UTF-8/LF 포함 65536바이트 상한을 생성 시 확인한다.

`finish_run()`은 차체가 모두 RESULT, 활성 운송/차량 구간 없음, 셀/차량 IDLE일 때 FINISHED 상태 사건→최종 전체 스냅샷→RUN_FINISHED를 기록한다. uniqueEventCount는 자신을 포함한 sourceSeq다. 이후 새 변경/스냅샷 사건을 만들지 않지만 최종 상태를 조회할 수 있다.

새 테스트 4개 포함 총 17개가 통과했다. C=2/3/4 각각 100대에서 작업 300·검사 100·운송 400·진입 300건과 최종 보존/보고를 확인했다. 검증 설정은 작업/적재 경로 200ms로 단축한 모델 시간이며 성능 실적이 아니다. 기본 데모는 기존 4/6/3초 구성으로 취소·고장/복구·부품 인계·HOLD 결과와 v1 사건을 출력한다. 모델 시간 계산이며 실제 장비/네트워크 연결이 아니다.

[작업 14 설명](<../../docs/work-notes/작업 14. 취소와 장애 복구 및 공장 모델 검증.md>) · S02~S07 완료 · 다음 S08-01. 명시적 송신 뒤 수집 worker가 관제에 자동 전달한다. 최소 SSE/Vue 연결은 S06에서 완료했고 일반 기동의 상시 생산은 후속이다.

## S03-04 원본 송신과 ACK

일반 기동은 기존 모델 초기화/heartbeat를 유지한다. 명시적 파일 송신은 원본 NDJSON을 한 프레임씩 읽고 해당 저장 ACK를 기다린다. 경로는 절대 경로를 사용한다.

```sh
INGESTION_TCP_HOST=127.0.0.1 INGESTION_TCP_PORT=9090 scripts/simulator.sh run --send-events /absolute/path/events.ndjson
```

파일 내용을 다시 직렬화하거나 eventId/sourceSeq/발생 시각을 바꾸지 않는다. 연결 2초·ACK 3초·최대 10회·지연 최대 30초다. version/kind/네 번호/해시와 성공 필드가 일치해야 head를 제거한다. 거절은 STOPPED_REJECTED, 한도 소진은 PAUSED_RETRY, 잘못된 재시도 설정은 PAUSED_CONFIG다. Sender.resume()은 원본을 보존한 채 명시적으로 다시 시도한다. 영구 거절 run을 재개하지 않는다.

SourceSession(model, sender)은 변경의 마지막에 원본 묶음을 목록에 넣으며 실패하면 tick 전체를 rollback한다. 900건/60MiB 이전에 제어 사건 자리를 남기고 PAUSED를 기록한다. hard cap은 1,000건/64MiB, 자동 재개는 500건 미만 AND 32MiB 미만이며 head 송신이 READY여야 한다. SourceSession.pause/resume는 작업자의 명시적 정지/재개이며 작업자 정지가 자동 용량 정지보다 우선한다. 정지 중 계속된 스냅샷 생성은 하지 않는다. 생산 변경은 session.change와 session.tick을 통한다.

SourceSession.send_head()는 저장 확인된 원본을 PendingQueue와 모델 저널에서 해제한다. sourceSeq/최종 uniqueEventCount는 유지한다. 미확인 목록과 공장 모델은 메모리라 프로세스 종료 후 복원되지 않는다. 원본 파일 재송신은 물리 상태 복원을 뜻하지 않는다. CLI 성공은 INGESTION_CONFIRMED이며 관제 반영/GUI LIVE는 false다.

```sh
PYTHONPATH=services/factory-simulator .build-cache/simulator-venv/bin/python -m unittest discover -s services/factory-simulator/tests -p test_sender.py -v
# 기존 Compose 실행 중, 새 run의 1대 흐름 확인 후 자기 run만 정리
python3 scripts/verify-ingestion-source.py
```

위 명령은 프로젝트 루트 기준이다. 새 송신 테스트 3개와 영향받는 기존 모델을 포함한 총 20개가 통과했다. 실제 연결에서는 원본/저장 ACK 39건·DB 원본 바이트/해시·재접속 중복 확인·미확인 목록 0건을 확인했다. 성능 측정이나 GUI 연결 증거는 아니다.

[작업 18 / S03-04](<../../docs/work-notes/작업 18. S03-04 Python ACK 처리와 제한된 재전송.md>) · [수집 서비스](../ingestion-service/README.md).

## S06-01 실제 최소 연결 시나리오

```sh
scripts/dev-stack.sh up
INGESTION_TCP_HOST=127.0.0.1 INGESTION_TCP_PORT=9090 scripts/simulator.sh run --connected-demo
```

기존 FactoryModel/SourceSession으로 새 run의 차체 한 대를 정상 등록한다. tick 기본100ms, 스냅샷 기본500ms로 실제 시간에 따라 진행하고 TCP ACK를 기다린다. 기존 예약/배차/픽업/운송/Bay 진입/조립/QC와 빈 AGV 귀환을 사용한다. 고정 PASS 시연이며 차체가 GOOD, 셀/차량이 IDLE이 되면 모델이 최종 전체 스냅샷과 RUN_FINISHED를 생성한다. 시험 위치 배치로 건너뛰지 않는다. 기본3셀 구성은 유지한다. 기본 시간 한도는300초이며 통신이 느리면 밀린 tick을 무리하게 한꺼번에 진행하지 않는다.

최초 출력의 runId/bodyId/tagId를 Vue http://127.0.0.1:5173에서 선택한다. `?run=실제runId`도 가능하다. 마지막 INGESTION_CONFIRMED는 수집 저장 확인이며 관제 반영/GUI 확인을 뜻하지 않는다. CLI는 operationsApplied/guiConfirmed를 성공으로 꾸미지 않는다. 관제 FINISHED/ARCHIVED, pending=0과 종료 순번 뒤 커서는 실제 API에서 따로 확인한다.

기본 로컬 기록은 `.build-cache/connected-demo/{runId}/`의 run.json/originals.ndjson/result.json이다. CONNECTED_DEMO_ARTIFACTS나 함수 evidence_root로 기록 루트를 지정할 수 있다. Docker 기본은 쓰기 가능한 `/tmp/factory-connected-demo`이며 컨테이너 삭제 후 보존되지 않는다. 별도 보존이 필요하면 쓰기 가능한 마운트 경로와 환경 변수를 함께 지정한다. 새 기본 볼륨이나 DB 마이그레이션은 추가하지 않았다. 정상 host 실행의 DB 행은 자동 삭제하지 않는다.

SIGINT/SIGTERM은 중단을 요청하고 미확인 원본을 기록한다. 시간 초과/실패는 수집된 원본을 지우거나 정상 종료로 표시하지 않는다. Python 프로세스의 물리 상태/미확인 목록을 재기동 후 자동 복원하는 기능은 없다. 일반 옵션 없는 기동은 여전히 초기화/heartbeat이며 연결 시나리오는 명시적 옵션이다.

[작업26/S06-01](<../../docs/work-notes/작업 26. S06-01 Python 최소 시나리오와 실제 전달.md>) · [실제 연결 검증](<../../docs/validation/최소 검증 시나리오와 도구.md>)


## S07 정상 등록 P0 관측 시나리오

현재 5대 시나리오는 **버퍼 용량을 초과하는 배차를 예방하는 동작**과 **의도적인 설비 장애·복구**를 한 실행에서 보여 준다. BUFFER_FULL은 정상적인 자원 대기이며 실행 오류가 아니다. ASM-02 진입을 잠시 보류해 대기 2대와 예약 1대로 용량 3을 채우고 신규 배차를 차단한다. 예약된 차체의 도착은 R→W 전환이며 슬롯 반환이 아니다. Bay 차체가 셀로 들어가야 슬롯을 반환하고 대기 운송을 재평가한다. 이후 ASM-01의 DOWN/복구는 별도로 주입한 장애다. 각 장면의 PAUSED는 관찰을 위한 실행 일시정지다.

AGV의 즉시 재배차로 장면이 건너뛰지 않도록, 첫 두 차체의 도착을 기다린 뒤 세 번째 차체의 ASM-01 진입을 허용한다. 이 대기는 시연 드라이버의 투입 제어이며 일반 모델의 슬롯·배차 규칙을 변경하지 않는다.

```sh
INGESTION_TCP_HOST=127.0.0.1 INGESTION_TCP_PORT=9090 scripts/simulator.sh run --connected-p0-demo
```

기본 C=3의 빈 공장에 차체5대와 부품 kit를 정상 등록한다. 기존 모델의 AGV 배차/운송·AMR 부품 운송·공정/검사 명령으로 진행한다. ASM-02 진입을 잠시 기다려 FULL_RESERVED(W2/R1/A0, 픽업 전 빈 AGV)→FULL_IN_TRANSIT(같은 예약, 실제 적재)→FULL_ARRIVED(W3/R0/A0와 앞 셀 BUFFER_FULL)→CELL_DOWN(ASM-01 정지)→SLOT_RELEASED(실제 복구와 첫 차체 셀 진입, W2/R0/A1)를 관측한다. 이후 정상 흐름을 끝내고 첫 차체HOLD/FAIL, 나머지4대GOOD/PASS와 모든 차량 귀환을 확인한다. 순간 이동이나 스냅샷 숫자 수작업으로 단계를 만들지 않는다.

일반 시연은 단계마다4초 동안 실제 PAUSED로 보고한 뒤 자동 진행한다. 기본 작업/운송 시간으로 수 분 걸릴 수 있다. 별도의 GUI 제어 명령은 아니다. 원본/run/단계/result는 기존 CONNECTED_DEMO_ARTIFACTS 규칙으로 남긴다. CLI의 INGESTION_CONFIRMED는 수집 ACK 확인이며 operationsApplied/guiConfirmed는 계속false다. 두 DB/GUI 성공은 별도 검증 근거가 필요하다.

SourceSession은 의도적인 PAUSED에서 publish_snapshot만 허용한다. 물리 tick이나 자동 재개는 허용하지 않으며 READY/미확인 대기 상한을 유지한다. 보고 중 BudgetPressure가 생겨도 정상 상태로 조작하거나 원본을 버리지 않는다. Python 미확인 목록은 계속 메모리이므로 비정상 프로세스 종료 후 물리 상태 복원은 보장하지 않는다.

`P0_DEMO_MARKERS`는 개발 검증에서 해당 단계의 .continue 파일을 기다리는 옵션이다. 단계660초 상한이며 관측 대기는 기본600초의 실제 진행 예산에서 제외한다. helper의 UI 확인 대기는600초다. 검증 소유 프로세스만 중단/재개하며 기존 서비스나 사용자의 실행을 멈추지 않는다. START_GATE는 새 UUID가 두 DB에 없음을 확인하기 전 TCP 쓰기를 막는다.

최소 신규2개와 송신 압력 회귀1개만 확인했다. 실제 구성은 작업200ms/경로1000ms로 줄여 흐름을 검증했으며 처리량/성능 성과가 아니다. [작업29](<../../docs/work-notes/작업 29. S07-01 실제 공장 SVG 지도와 차량·슬롯.md>) · [공유 검증](<../../docs/validation/최소 검증 시나리오와 도구.md>) · [Vue 안내](../factory-console/README.md).

## S09 완료와 재실행

현재 정상 생산은 `--connected-demo`(1대)와 `--connected-three-demo`(3대)를 지원한다. 두 모드 모두 정상 등록과 실제 운송·공정·검사를 사용하고 PASS/GOOD으로 완료한다. 3대 실행도 기본 경로·용량 규칙을 사용한다. Windows 명령과 웹 시작 버튼은 [Windows 실행 안내](<../../docs/development/Windows Docker 없이 실행.md>)를 따른다.

[실제 측정/P0 완료표](<../../docs/development/S09 측정·완료 기록.md>) · [처음 실행/기존 데이터/복구/시연](<../../docs/development/초기 실행·재실행·복구·시연.md>) · [새 실제 시연 캡처/단계 재생](<../../docs/development/s09-demo/index.html>).

S09-01~04를 완료했습니다. 측정은 별도 네이티브 검증 DB/임의 loopback 포트를 사용하며 개발 Compose DB/볼륨은 유지했습니다. 정상25.63~25.72건/s·작은 화면 반영 p95 약98ms, 높은 입력 목표 미생성·업무 전달 지연을 구분합니다. SQL 병목이 확인되지 않아 새 index/DDL/의존성은 추가하지 않았습니다. 수집 Flyway1/2·관제1 그대로이며 같은 기존 data 재시작의 선택8개 표 지문이 일치했습니다. 일반 기동은 자동 생산하지 않습니다.
