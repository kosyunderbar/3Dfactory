# TCP 사건 수집 서비스

> S03-01~04 완료 · Spring Boot 4.1.1 / Java 21 / PostgreSQL 17.11 · S05-01~03 완료 · 다음 S06-01

Python의 UTF-8 NDJSON 사건을 TCP로 받아 v1 형태/식별자를 검증하고 원본·outbox·run 전달 정보를 함께 저장한다. COMMIT 확인 뒤에만 RECEIVED를 응답하며 동일 원본은 DUPLICATE_RECEIVED다. ACK는 수집 저장 확인이다. S05의 단일 worker가 저장 원본을 관제에 자동 HTTP 전달하며 성공/중복 성공 뒤에만 전달 커서를 증가시킨다.

## 기동

프로젝트 루트에서 기존 DB 환경을 사용하는 전체 기동은 `scripts/dev-stack.sh up`이다. 이 서비스만 변경했으면 다음과 같이 반영한다. 기존 볼륨은 보존된다.

```sh
scripts/dev-stack.sh compose up -d --build --wait ingestion-service
```

일반 단독 실행은 [서비스 설정 안내](../README.md)의 DB/앱/Flyway 계정 환경 변수 5개를 요구한다.

| 설정 | 기본/의미 |
|---|---|
| INGESTION_TCP_ADDRESS | 127.0.0.1; Compose 컨테이너 내부 0.0.0.0 |
| INGESTION_TCP_PORT | 9090; Compose 호스트는 127.0.0.1에만 공개 |
| INGESTION_REJECTION_LOG | ./logs/ingestion-rejections.ndjson; Compose /var/log/factory/rejections.ndjson |
| INGESTION_HTTP_ADDRESS/PORT | 기존 HTTP 127.0.0.1:8081, /readyz·/livez |
| OPERATIONS_BASE_URL | http://127.0.0.1:8082; Compose http://operations-service:8082 |
| INGESTION_DELIVERY_ENABLED | true. 경계별 시험에서만 false로 끄고 readiness에서 delivery 제외 |

일반 `/readyz`는 DB·TCP와 전달 worker의 실행 여부를 포함한다. 상대 관제의 중단은 수집 준비 실패로 만들지 않고 outbox 재시도/보류로 드러낸다. `bootstrap`은 TCP/DB를 만들지 않고 준비 상태 503을 유지한다. 단독 저장 테스트는 `factory.tcp.enabled=false`, `factory.delivery.enabled=false`와 readiness의 해당 항목 제외를 명시한다. 업무 REST는 관제 S04, 전달 진단은 S05에 구현했다. 관제 SSE/최소 실제 Vue 연결은 S06에서 완료했고 전체 관제 GUI는 S07이다. 수집 서비스는 화면 상태를 만들지 않는다.

Compose의 `ingestion-diagnostics` 볼륨은 거절 로그를 보존한다. 실행 사용자 10001이 쓸 수 있도록 이미지의 로그 경로를 준비했다. 파일은 10MiB×3, 미리보기 원본은 1KiB 이하다. 기존 postgres-data는 그대로 사용한다.

## 경계와 코드

- [FrameDecoder.java](src/main/java/dev/factory/ingestion/receiver/FrameDecoder.java): LF 포함 65,536바이트, UTF-8 바이트 조립, 부분 프레임 첫 바이트부터 3초.
- [TcpReceiver.java](src/main/java/dev/factory/ingestion/receiver/TcpReceiver.java), [AdmissionQueue.java](src/main/java/dev/factory/ingestion/receiver/AdmissionQueue.java): 연결 8개, 대기 128프레임/8MiB, 접수 worker 하나.
- [Protocol.java](src/main/java/dev/factory/ingestion/receiver/Protocol.java): 엄격한 JSON·v1 봉투/17종 payload 형태/값·ACK.
- [EventStore.java](src/main/java/dev/factory/ingestion/receiver/EventStore.java): 같은 원본과 ID/순번/source 충돌, 신규 상한, 트랜잭션, COMMIT 뒤 확인 응답.
- [RejectionLog.java](src/main/java/dev/factory/ingestion/receiver/RejectionLog.java): 정상 DB 원본과 분리된 제한 로그.

입력/기존 원본 확인이 먼저다. 신규 사건만 미래 5초·outbox 5,000건/128MiB·run 보관 50,000건/512MiB·전체 250,000건/1GiB 제한을 받는다. 격리/보류도 미전달에 포함한다. byte/hash 비교는 LF를 제외한 최초 UTF-8 원본이다. 반영 순서/업무 참조는 [v1 계약](../../contracts/v1/delivery.md)을 따른다.

## 필요한 최소 검증

```sh
# 자체 단위 경계만: 실제 DB 테스트는 기본 빌드에서 생략
scripts/service-maven.sh ingestion-service --offline --batch-mode --no-transfer-progress -Dtest=ReceiverUnitTests test
# PostgreSQL 17.11 도구 준비 후, 격리 DB에서 커밋/rollback/ACK 유실까지
python3 scripts/verify-databases.py --suite ingestion
# 기존 Compose에서 Python->TCP->자동 HTTP->관제 DB/REST, 새 자기 UUID만 정리
python3 scripts/verify-delivery.py
```

S03 당시 Java 7개(단위 3·실제 DB/TCP 3·기존 bootstrap 1), Python 실제 연결 원본/ACK 39건이 통과했다. DB 테스트는 FACTORY_INGESTION_TESTS=true일 때만 실행한다. 원본/outbox 제약과 rollback 증거는 실제 PostgreSQL이며 가짜 DB로 대체하지 않았다. 첫 검증 명령과 전체 DB 검증을 변경 없이 반복 실행할 필요는 없다.

[작업 15 / S03-01](<../../docs/work-notes/작업 15. S03-01 TCP 입력 조립과 수신 제한.md>) · [작업 16 / S03-02](<../../docs/work-notes/작업 16. S03-02 사건 검증과 중복 구분.md>) · [작업 17 / S03-03](<../../docs/work-notes/작업 17. S03-03 원본과 전달 대기 저장 및 ACK.md>) · [작업 18 / S03-04](<../../docs/work-notes/작업 18. S03-04 Python ACK 처리와 제한된 재전송.md>)

## S05 자동 전달과 재시작 복구

[DeliveryWorker](src/main/java/dev/factory/ingestion/delivery/DeliveryWorker.java)는 단일 인스턴스·단일 worker로 한 HTTP만 진행한다. 실행별 순환으로 next_source_seq 한 건을 선택하고, [DeliveryStore](src/main/java/dev/factory/ingestion/delivery/DeliveryStore.java)는 발송 전 시도 예약과 결과 저장을 짧은 트랜잭션으로 나눈다. HTTP 중 DB 잠금을 유지하지 않는다. [OperationsClient](src/main/java/dev/factory/ingestion/delivery/OperationsClient.java)는 저장 원본/해시/최초 수신 시각을 그대로 보내며 전체 요청/응답 5초·연결 1초·응답 8KiB로 제한한다. [DeliveryWire](src/main/java/dev/factory/ingestion/delivery/DeliveryWire.java)가 v1 답장의 모든 필드와 HTTP 상태/번호/해시를 검증한다.

완료 표시와 커서 증가는 한 트랜잭션이다. 응답 유실/완료 저장 실패는 같은 원본 재전달로 확인한다. 500ms부터 최대30초의 backoff/jitter, 최초 포함20회 한도, 순번/의존성30초 보류를 적용한다. 영구 거절은 QUARANTINED+BLOCKED를 함께 저장하고 원본/답장을 보존한다. 뒤 순번을 건너뛰지 않으며 다른 실행은 계속 진행한다. RUN_BLOCKED 응답 자체는 아직 처리하지 못한 원본을 임의로 격리하는 근거로 쓰지 않는다.

재기동은 DB 책갈피·시도 횟수·다음 시각을 유지한다. HTTP 직전 종료는 실제 전송 여부가 불명확할 수 있어 예약된 시도 횟수를 보수적으로 유지한다. [수집 V2](src/main/resources/db/migration/V2__delivery_attempts_and_resumption_audit.sql)는 기존 V1을 바꾸지 않고 total_attempt_count/last_attempt_at과 delivery_action 재개 기록만 추가한다. 현재 수집4표·관제13표다.

### 내부 진단과 명시적 재개

- GET /internal/v1/runs/{runId}/delivery-status: v1 정확한16필드, 미전달 수/바이트/가장 오래된 수신 시각·커서/중단 원인·누적 횟수·현재 TCP 연결 표본. [화면 계약](../../contracts/v1/monitoring.md).
- GET /internal/v1/runs/{runId}/outbox?afterSeq=0&limit=50&status=QUARANTINED: 순번 오름차순의 진단 페이지, 기본50/최대200·응답 최대512KiB. status는 생략 가능하며 원본 본문은 노출하지 않는다. 상태는 조회 사이 변경될 수 있어 이 페이지를 확정 이력 fence로 사용하지 않는다.
- POST /internal/v1/runs/{runId}/delivery-resume: 정확히 {sourceSeq,operatorId,reason}, 요청 최대2KiB. 현재 head가 일치하는 PAUSED_RETRY/DEPENDENCY/CONFIG만 허용한다. 이번 시도 묶음만 초기화하고 누적 횟수·원본·해시는 유지하며 이전 상태/이유/운영자/시각을 함께 저장한다. BLOCKED/격리/커서 건너뛰기는 거절한다.

모든 내부 API는 no-store다. operatorId는 영문/숫자/밑줄/하이픈1~64자, reason은 공백만 허용하지 않으며 UTF-8 최대1024바이트다. 이 내부 도구는 사용자 인증 시스템이 아니다. 순번 범위의 과거 원본 재전달 도구는 이번 작업에 포함하지 않는다.

```sh
# 실제 등록된 runId로 변경. 먼저 상태/문제 기록을 확인한다.
python3 scripts/delivery-control.py status run-20261005-00000000000000000000000000000000
python3 scripts/delivery-control.py outbox run-20261005-00000000000000000000000000000000 --status QUARANTINED
# 원인 해결과 현재 head 확인 후 명시적으로 재개
python3 scripts/delivery-control.py resume run-20261005-00000000000000000000000000000000 --source-seq 8 --operator local-user --reason '접속 복구 확인'
```

sourceConnected는 살아 있는 TCP 연결에서 해당 실행의 수집 성공이 확인됐을 때만 true다. 기존 DB 행이나 재시작만으로 생산자 연결을 추정하지 않는다. retryCount는 첫 시도 이후 DB에 예약된 추가 전달 시도 수이며 실제 HTTP 시작 직전 종료도 포함될 수 있다. rejectedCount는 등록된 run의 TCP 영구 거절 횟수와 관제 영구 거절된 고유 사건 수다. 아직 등록되지 않은 잘못된 입력은 기존 제한 로그로 남긴다.

### S05에 필요한 최소 검증

```sh
# 새 격리 PostgreSQL17.11 두 DB와 실제 관제 프로세스; 총8개
python3 scripts/verify-databases.py --suite delivery
# 이미 기동한 Compose, 서비스 중단 없는 정상60건
python3 scripts/verify-delivery.py
# 별도 개발 환경에서만: 관제 중단->대기 수집->수집 재시작->관제 복구
python3 scripts/verify-delivery.py --with-restarts
```

이번에는 Java8개와 Compose의 마지막 명령 한 번을 수행했다. 나머지 둘을 동일 변경에서 반복할 필요는 없다. Java는 전달 판정1·실제 두 DB/TCP/HTTP3·영향받은 저장 경계3·bootstrap1이다. 응답 유실/수집 완료 저장 rollback·관제 DB 중단·순번/의존성·영구 거절·20회 보류와 재개를 묶었다. Compose는 정확한 원본60건 자동 반영·pending0/커서61·LIVE→FINISHED/ARCHIVED·HOLD/FAIL·작업3/운송6/검사1을 확인했다.

검증 helper는 새 UUID의 두 DB 기존 행0건을 확인하고 성공한 자기 run만 정리한다. 재시작 옵션은 다른 run의 미전달이 있으면 중단을 거절한다. 실패 기록은 보존하고 중단한 관제는 finally에서 복원한다. DB/볼륨을 초기화하지 않는다. `verify-ingestion-source.py`는 S05 이후 자동 전달을 반영해 기본 `verify-delivery.py`로 연결하는 호환 진입점이다. 과거 S03의 PENDING/커서1 결과는 당시 기록으로만 읽는다.

[작업23/S05-01](<../../docs/work-notes/작업 23. S05-01 영속 outbox와 자동 HTTP 전달.md>) · [작업24/S05-02](<../../docs/work-notes/작업 24. S05-02 전달 결과와 순서·격리.md>) · [작업25/S05-03](<../../docs/work-notes/작업 25. S05-03 재시작 복구와 전달 진단·재개.md>)

## S09 완료와 재실행

[실제 측정/P0 완료표](<../../docs/development/S09 측정·완료 기록.md>) · [처음 실행/기존 데이터/복구/시연](<../../docs/development/초기 실행·재실행·복구·시연.md>) · [새 실제 시연 캡처/단계 재생](<../../docs/development/s09-demo/index.html>).

S09-01~04를 완료했습니다. 측정은 별도 네이티브 검증 DB/임의 loopback 포트를 사용하며 개발 Compose DB/볼륨은 유지했습니다. 정상25.63~25.72건/s·작은 화면 반영 p95 약98ms, 높은 입력 목표 미생성·업무 전달 지연을 구분합니다. SQL 병목이 확인되지 않아 새 index/DDL/의존성은 추가하지 않았습니다. 수집 Flyway1/2·관제1 그대로이며 같은 기존 data 재시작의 선택8개 표 지문이 일치했습니다. 일반 기동은 자동 생산하지 않습니다.

Java 계측은 `-Dfactory.measurement.file=<전용 CSV 경로>`에서만 켭니다. 기본은 비활성입니다. 단일 프로세스 monotonic 구간과 호스트 wall clock을 기록하며 행 상한2,000,000, 오류 시 계측 중단/업무 계속을 적용합니다. CSV를 운영 지표나 새로운 API 계약으로 사용하지 않습니다.
