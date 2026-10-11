# 서비스 실행 기반

> S01-01~04 · Spring Boot 4.1.1 / Java 21 / Maven 3.10.0 / Wrapper 3.3.4  
> 현재 구현: 각 앱의 빌드·설정·bootstrap 기동, 두 DB·계정·Flyway V1 준비/실제 검증. readiness와 Compose·Python/Vue 기본 앱, S02 전체의 Python 공장 모델·취소/장애·부품 AMR·v1 사건/전체 스냅샷까지 준비했다. 2~4칸 각 100대의 모델 정합성을 확인했다. 일반 기동은 자동 생산을 시작하지 않는다. S06에서 명시적 최소 연결 시나리오를 추가했다. S03의 TCP 수집·원본/outbox 동시 저장·커밋 후 ACK·Python 재전송까지 완료했다. S04 관제 업무 반영·영속 중복 처리·메타/이력/최신 상태·REST SQL·신선도/알람까지 완료했다. S05 자동 outbox 전달·수집 진단 제공/재개·재시작 복구까지 완료했다. S06의 비차단 SSE/실제 최소 Vue 셀·태그 연결까지 완료했다. 전체 업무 GUI는 S07에서 완료했다.

| 앱 | 기본 HTTP 주소 | 자체 DB 설정 이름 | 역할 |
|---|---|---|---|
| ingestion-service | 127.0.0.1:8081 | INGESTION_DB_URL / INGESTION_DB_USERNAME / INGESTION_DB_PASSWORD | S03 TCP 수집·원본/outbox 완료. S05 자동 전달/진단 완료 |
| operations-service | 127.0.0.1:8082 | OPERATIONS_DB_URL / OPERATIONS_DB_USERNAME / OPERATIONS_DB_PASSWORD | S04 업무 반영·이력·REST SQL·알람 완료. S06 SSE 전체 묶음 완료 |

각 디렉토리에 pom.xml·Maven Wrapper·main·설정·테스트가 있어 다른 앱을 먼저 빌드할 필요가 없다. 앱끼리 코드/DB 객체를 참조하는 공유 모듈은 없다. S01-02에서 PostgreSQL 17.11의 두 DB와 서비스별 Flyway V1을 준비·검증했다. [DB 실행 안내](../infrastructure/postgresql/README.md)를 따른다. JPA·H2·브로커는 추가하지 않았다.

## 빌드와 최소 테스트

프로젝트 루트에서 실행한다. Java 21 JDK, curl 또는 wget, unzip(Unix/macOS), 최초 의존성 다운로드를 위한 인터넷이 필요하다. macOS에서는 helper가 설치된 Java 21을 찾고, 다른 환경에서는 JAVA_HOME 또는 PATH로 Java 21을 지정한다.

```sh
scripts/service-maven.sh ingestion-service --batch-mode --no-transfer-progress verify
scripts/service-maven.sh operations-service --batch-mode --no-transfer-progress verify
```

일반 verify는 컴파일→기본 테스트→실행 JAR 생성을 수행한다. 수집 앱은 기존 골격 1개와 수집 단위 경계 3개·전달 판정 1개, 관제 앱은 판정2개·비차단 전송 채널1개·기존 골격1개다. DatabaseMigrationTests는 FACTORY_DATABASE_TESTS=true일 때만 실행하며 기본 빌드에서는 건너뛴다. 실제 DB 검증은 DB 안내의 새 클러스터 명령을 사용한다. 테스트는 bootstrap 모드에서 실제 임시 포트로 웹 서버를 띄우며, DataSource/Flyway가 생성되지 않고 /readyz 503, /livez 200인지 실제 HTTP로 확인한다. 수집 DB/TCP 실제 검증은 별도 --suite ingestion에서 FACTORY_INGESTION_TESTS=true로 실행한다. 관제 실제 DB/HTTP는 --suite operations의 4개 시나리오로 확인한다. 코드 변경 영향이 한 앱이면 그 앱만 검증한다.

결과 파일은 각각 `target/ingestion-service-0.1.0-SNAPSHOT.jar`, `target/operations-service-0.1.0-SNAPSHOT.jar`다. 테스트 결과는 각 앱의 `target/surefire-reports/`에 있다. 캐시·target은 .gitignore 대상이다.

Maven을 시스템에 별도로 설치할 필요는 없다. helper는 각 앱의 정식 mvnw를 사용하고 다운로드/의존성 캐시를 `.build-cache/maven/`에 둔다. 각 앱 안에서 `./mvnw verify`도 가능하지만 기본 Maven 사용자 캐시를 사용한다. Windows에서는 해당 앱의 `mvnw.cmd verify`를 사용한다(Windows 실행은 이번 환경에서 검증하지 않음).

## DB 없는 골격 실행

터미널 두 개에서 앱을 하나씩 실행한다.

```sh
scripts/service-maven.sh ingestion-service spring-boot:run -Dspring-boot.run.profiles=bootstrap
```

```sh
scripts/service-maven.sh operations-service spring-boot:run -Dspring-boot.run.profiles=bootstrap
```

`bootstrap`은 DB·Flyway 자동 구성을 제외하는 **명시적인 골격 확인 모드**다. 기본 프로필로 자동 선택하지 않는다. 웹 서버가 시작됐어도 DB/수집/관제가 준비됐다는 뜻이 아니다. bootstrap에서는 업무 컨트롤러를 등록하지 않아 `/`와 `/api/v1/…`은 404다. 일반 관제 모드의 REST API는 S04에서 구현했다. 가짜 정상 응답/데모 공장 상태를 만들지 않았다. 종료는 Ctrl+C.

패키징한 JAR도 같은 방식으로 실행할 수 있다.

```sh
java -jar services/ingestion-service/target/ingestion-service-0.1.0-SNAPSHOT.jar --spring.profiles.active=bootstrap
java -jar services/operations-service/target/operations-service-0.1.0-SNAPSHOT.jar --spring.profiles.active=bootstrap
```

각 java 명령은 별도 터미널에서 실행한다. Java 21이 PATH에 있어야 한다.

## 일반 실행과 설정 경계

bootstrap을 지정하지 않은 일반 실행은 자기 앱의 DB URL·일반 계정 사용자/암호·Flyway 계정 사용자/암호, 총 5개 설정이 필요하다. *_MIGRATION_USERNAME/PASSWORD를 추가로 전달하며 일반 계정은 ingestion_app/operations_app, Flyway 계정은 ingestion_migrator/operations_migrator다. 암호를 코드/문서에 넣지 않는다. 환경 변수를 생략해도 임의의 로컬 계정·가짜 메모리 DB로 기동하지 않는다. DB 없이 일반 모드 기동은 실패하는 것이 정상이다. 초기 DB는 [전용 인스턴스 준비](../infrastructure/postgresql/README.md)를 먼저 수행한다. 검증 서버는 확인 후 종료했고, Compose 구성은 [전체 실행 안내](../infrastructure/README.md)에 준비했다.

Flyway는 `classpath:db/migration`을 사용하고 누락된 경로는 오류, clean은 금지, migrate 시 검증을 켠다. 서비스별 디렉토리에 독립 V1 SQL을 두었다. 일반 DataSource와 Flyway 연결 계정을 분리한다. 연결 풀 최대4, 접속 대기3초, 초기 접속 실패 대기3초다. 자기 DB 쓰기와 다른 DB/앱 DDL 거절, 반복 마이그레이션의 데이터 유지는 실제 17.11에서 확인했다. 업무 쿼리/처리 검증은 해당 구현 작업에서 진행한다.

HTTP 주소/포트는 서비스별 `INGESTION_HTTP_ADDRESS/PORT`, `OPERATIONS_HTTP_ADDRESS/PORT`로 재정의할 수 있다. 기본은 localhost이고 Compose는 0.0.0.0의 컨테이너 주소를 사용하고 호스트 공개 포트는 127.0.0.1로 제한한다. readiness는 /readyz, liveness는 /livez다. 로그에는 앱 이름을 붙인다. 설정/비밀번호 전체를 출력하는 진단은 넣지 않았다. 수집 TCP의 기본 주소는 127.0.0.1:9090이며 INGESTION_TCP_ADDRESS/PORT로 변경한다. 일반 수집 readyz는 DB+TCP+전달 worker 실행 여부를 확인한다. 상대 관제 중단은 이 준비 실패 대신 outbox 대기/재시도로 드러낸다. 내부 업무 API는 S04에서 구현했다. INGESTION_DIAGNOSTIC_URL로 내부 수집 진단 기본 주소를 지정하며 S05에서 내부 delivery-status를 구현했다.

[고정 버전과 다운로드 근거](../docs/development/실행 버전과 빌드 기준.md) · [작업 5 해설](<../docs/work-notes/작업 5. 두 Spring 앱의 실행 기반.md>) · [개발 계획](<../가상 제조공장 실시간 통합 관제 시스템 - 단계별 개발 계획.md>)

## 전체 기동과 Python/Vue

[전체 실행 안내](../infrastructure/README.md)의 scripts/dev-stack.sh로 PostgreSQL과 네 앱을 함께 기동/보존 종료한다. 정상 readiness는 자기 DB 연결을 포함하며 bootstrap은 503이다. 아직 제조 데이터 LIVE를 표시하는 업무 진단은 아니다.

- [Python 시뮬레이터](factory-simulator/README.md): Python 3.12 가상환경·공장 설정·차체/태그 등록·단일 위치 기초·unittest.
- [Vue 관제 앱](factory-console/README.md): Vue 3·JavaScript·Vite와 실제 관제 준비 상태 확인 화면.
- [작업 7](<../docs/work-notes/작업 7. Compose와 실행 준비 상태.md>) · [작업 8](<../docs/work-notes/작업 8. Python과 Vue 기본 앱.md>): 쉬운 역할 설명과 최소 검증 결과.

[S03 TCP 수집 실행/검증 안내](ingestion-service/README.md) · [S03 Python 송신 안내](factory-simulator/README.md).

[S04 관제 API 실행/검증 안내](operations-service/README.md). S04는 실제 PostgreSQL/HTTP4·판정2·bootstrap1의 총7개와 Compose의 명시적 사건60건 반영을 확인했다. S04 당시 진단 제공 미연결은 UNKNOWN으로 확인했다. 이후 S05 자동 전달/진단과 S06 SSE/최소 실제 Vue 연결까지 완료했다. 전체 업무 GUI는 S07에서 완료했다.

[S05 수집 자동 전달/진단 안내](ingestion-service/README.md). `python3 scripts/verify-databases.py --suite delivery`는 새 격리 클러스터와 실제 관제 프로세스에서 전달 판정1·두 DB/TCP/HTTP3·영향받은 기존 저장3·bootstrap1의 8개만 실행한다. 실제 DB 시험은 helper의 FACTORY_DELIVERY_TESTS=true일 때만 활성화한다. 변경되지 않은 관제 전체/Python/GUI 시험은 반복하지 않았다. 수집 Flyway는 기존 V1+추가 V2, 관제는 V1 유지다.


## 실제 관제 화면 — S07 완료

현재 factory-console은 Three.js 3D/2D 대체 지도·AGV/AMR 추적·태그 검색/상세·품질 ECharts·알람·기록을 REST/SSE에 연결한다. 로컬 Vite에서 1대/3대 정상, 5대 장애·수동 복구를 시작·중단하고 점검·조치할 수 있다. AMR 실제 재고 공급을 포함한 [현재 기능과 검증 범위](<../docs/development/현재 기능과 검증 범위.md>)를 따른다. S07은 기존 Java/DB/서비스 책임·Flyway를 바꾸지 않았다. [Vue 안내](factory-console/README.md)와 [작업32](<../docs/work-notes/작업 32. S07-04 선택·조회 순서와 모바일·키보드 접근.md>)를 따른다. S07 완료 당시 다음은 S08-01이었다.

## S08 장애·복구 통합 완료

S08-01~04에서 별도 PostgreSQL과 두 서버로 예약 취소/반환·목적 셀 정지 중 도착·확인/복구, TCP ACK 유실/재전송·12초 보고 단절, 양 서비스와 개별 DB·PostgreSQL 재시작을 확인했다. 최종 5대 실행 원본216건과 100대 실행 원본3,533건은 두 DB에서 순번·바이트·해시가 일치했다. 100대의 2,764 tick에서 단일 위치/용량을 확인하고 중간 전체 스냅샷28개와 최종 상태를 관제 API와 비교했다. 작업300/검사100/운송400·PASS80/FAIL20, 검사/운송 원본 각각10회 재전송의 실적 증가0·run 격리가 통과했다. 실제 Chrome의 SSE 단절/복구·태그 선택/마지막 값 보존은 별도 실행 증거를 명시해 재사용했다. 기존 Java 관련2개만 선택 실행했고 전체 테스트·새 의존성·DDL·운영 코드 변경은 없다. 기존 스택과 흰색/네이비/파란색 UI·개발 DB/볼륨을 유지했다. 논리 공정의 정확성 검증이며 S08 당시의 기능 정확성 기록이며 실제 성능은 이후 S09에서 측정했다.

[S08 결과/재실행](<../docs/development/S08 장애·복구 통합 검증.md>). 검증 전용 native PostgreSQL/Java를 사용하므로 기존 Compose를 중단하거나 볼륨을 삭제하지 않는다. 현재 S09까지 완료했다.

## S09 완료와 재실행

[실제 측정/P0 완료표](<../docs/development/S09 측정·완료 기록.md>) · [처음 실행/기존 데이터/복구/시연](<../docs/development/초기 실행·재실행·복구·시연.md>) · [새 실제 시연 캡처/단계 재생](<../docs/development/s09-demo/index.html>).

S09-01~04를 완료했습니다. 측정은 별도 네이티브 검증 DB/임의 loopback 포트를 사용하며 개발 Compose DB/볼륨은 유지했습니다. 정상25.63~25.72건/s·작은 화면 반영 p95 약98ms, 높은 입력 목표 미생성·업무 전달 지연을 구분합니다. SQL 병목이 확인되지 않아 새 index/DDL/의존성은 추가하지 않았습니다. 수집 Flyway1/2·관제1 그대로이며 같은 기존 data 재시작의 선택8개 표 지문이 일치했습니다. 일반 기동은 자동 생산하지 않습니다.
