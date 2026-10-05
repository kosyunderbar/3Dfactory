# 전체 개발 환경 실행

> S01 실행 기반 + S03 TCP 수집/송신 + S04 관제 업무/REST/알람 · S05 자동 전달/진단/복구 · S06 실제 SSE/Vue 최소 연결 · S07 전체 관제 GUI 완료

다른 컴퓨터에 clone하거나 기존 저장소에 pull한 뒤 실행·개발하려면 [다른 컴퓨터 실행·개발 안내](<../가상 제조공장 실시간 통합 관제 시스템 - 다른 컴퓨터 실행·개발 안내.md>)를 먼저 따른다. OS별 준비, 최초 기동, 데이터 보존 업데이트와 서비스별 개발 방법을 설명한다.

## 처음 실행

Docker Engine과 Compose v2 이상, BuildKit/Buildx가 필요하다. 이번 환경의 실제 버전은 Docker 29.8.2 / Compose 5.6.0 / Buildx 0.37.2다. Docker Desktop 등 기존 Engine을 사용할 수 있다. 프로젝트 루트에서 실행한다.

```sh
scripts/dev-stack.sh env
scripts/dev-stack.sh check
scripts/dev-stack.sh up
scripts/dev-stack.sh status
```

`env`는 `.env`를 권한 0600으로 만들고 5개의 로컬 암호를 무작위 생성한다. 파일이 있으면 **덮어쓰지 않고 종료**한다. 이미 준비했다면 생략한다. [.env.example](../.env.example)은 설정 이름과 기본 포트의 예시다. `CHANGE_ME`를 실제 암호로 사용하지 않는다. `.env`가 Spring/브라우저 소스에 포함되거나 화면으로 전달되지 않는다. 필수 암호가 비어 있으면 Compose 설정 단계부터 실패한다.

`up`은 독립 이미지를 빌드한 뒤 모든 컨테이너의 기본 실행 준비 상태를 기다린다. PostgreSQL 준비 이후 각 Spring 앱이 자기 Flyway를 실행한다. 앱/화면/Python 사이에 불필요한 기동 의존성을 추가하지 않았다. 수집 서비스를 멈춰도 관제·화면·Python 프로세스는 유지된다. DB 중단은 두 앱의 준비 상태에 영향을 준다.

| 주소/대상 | 현재 의미 |
|---|---|
| http://127.0.0.1:5173 | 실제 Vue 셀/버퍼 관측·차체/태그 상세 |
| http://127.0.0.1:8081/readyz | 수집 앱 + 자기 DB + TCP 리스너 + 전달 worker 실행 상태 |
| 127.0.0.1:9090 (TCP) | S03 NDJSON 사건 수집·원본/outbox 저장 ACK |
| http://127.0.0.1:8082/readyz | 관제 앱 + 자기 DB 준비 상태 |
| 각 Spring 앱의 `/livez` | 프로세스 기본 기동 상태; DB 연결 제외 |
| Vue 서버의 `/healthz` | 정적 화면 제공 준비 상태 |
| Python 컨테이너 health | S02-01 모델 초기화 이후 기본 heartbeat; 공장 운전 시작 아님 |

일반 모드의 DB 연결 실패는 `/readyz` 503, 프로세스가 살아 있으면 `/livez` 200이다. bootstrap도 `/readyz` 503이다. 정상 준비는 `/readyz` 200이며 DB 준비를 뜻한다. S06의 REST/SSE·Vue 연결과 별개로 /readyz 성공만으로 제조 데이터 LIVE를 뜻하지 않는다. 상대 관제 중단은 수집 기동 실패로 만들지 않고 대기/재시도로 처리한다. TCP 수집과 저장 ACK는 S03에서 구현했다. 제조 데이터의 LIVE/STALE 등은 S00의 별도 화면 계약에 따른다. DB는 기본적으로 호스트에 포트를 공개하지 않으며 화면/앱 공개 포트는 127.0.0.1에만 바인딩한다.

## 종료·로그·서비스별 조작

```sh
scripts/dev-stack.sh logs operations-service
scripts/dev-stack.sh compose stop ingestion-service
scripts/dev-stack.sh compose up -d --wait ingestion-service
scripts/dev-stack.sh down
```

로그는 각 앱 표준 출력으로 모으며 컨테이너별 10MB × 3파일로 제한한다. `logs`는 최근 100줄을 보여준다. `down`은 컨테이너/네트워크를 종료하며 **DB 및 수집 거절 로그 볼륨을 보존**한다. helper에 데이터 초기화/볼륨 삭제 명령은 없다. 이후 `up`은 기존 DB를 사용하고 Flyway 적용 이력을 확인한다. 적용한 V1을 수정하거나 암호 파일만 새로 생성해 기존 DB 암호가 바뀌었다고 가정하지 않는다.

PostgreSQL 이미지의 초기 SQL은 빈 데이터 디렉토리에서만 실행된다. 이미 프로젝트 역할/DB가 있으면 수동 초기화 SQL도 덮어쓰기를 거절한다. 초기화가 중간 실패했다면 로그와 현재 역할/DB를 확인해 원인을 고친다. 볼륨 삭제를 기본 해결법으로 사용하지 않는다. 상세 계정·구조는 [PostgreSQL 안내](postgresql/README.md)를 따른다.

별도 Compose 프로젝트가 필요하면 `FACTORY_COMPOSE_PROJECT=별도이름`을 helper 실행 환경에 지정한다. 같은 호스트 포트를 쓰는 환경은 동시에 기동하지 않는다. 포트는 루트 `.env` 또는 해당 환경 변수로 변경할 수 있다.

## 이번 macOS의 선택적인 로컬 Engine

이 컴퓨터에는 기존 Docker/Node가 없어 공식 배포본을 로컬 캐시에 준비했다. 다른 환경에 이 도구를 필수로 설치할 필요는 없다. 이 helper는 **macOS arm64 전용**이며 Docker 제품 스택을 실행하는 개발 도구다.

```sh
python3 scripts/prepare-dev-tools.py docker
scripts/local-docker.sh start
scripts/dev-stack.sh up
```

공식 Lima 2.2.1의 Docker 템플릿과 macOS VZ를 사용한다. VM은 CPU 2 / 메모리 4GiB / 디스크 20GiB, 프로젝트 폴더만 읽기 전용 마운트다. CLI·Compose·Buildx·Lima 바이너리는 `.build-cache/`에 둔다. 시스템 Docker context나 기본 사용자 설정을 변경하지 않는다. 로컬 CLI가 사용될 때만 helper가 해당 Engine 소켓과 프로젝트 Docker 설정을 선택한다. 직접 docker를 실행하려면 scripts/docker-env.sh와 같은 환경을 지정하거나 helper의 compose 하위 명령을 사용한다.

**이 로컬 검증 VM의 상태와 DB 볼륨은 `/tmp/factory-lima-s01`의 가상 디스크에 있다.** 프로젝트 경로가 길어 macOS Unix 소켓 길이 제한을 피하기 위한 검증 경로다. Compose down/up 및 VM stop/start에는 유지되지만 OS의 임시 폴더 정리까지 영속성을 보장하는 상시 저장소가 아니다. 장기간 데이터를 보관할 때는 일반 Docker Engine의 지속 저장소와 DB 백업을 사용한다. Lima 이미지 다운로드 캐시는 macOS의 기본 Lima 캐시에도 생긴다.

종료 순서는 `scripts/dev-stack.sh down`, `scripts/local-docker.sh stop`이다. 다음 실행은 `scripts/local-docker.sh start`, `scripts/dev-stack.sh up`이다. 도구 고정값은 [local-tools.lock.json](local-tools.lock.json), 이미지 digest는 [images.lock.json](images.lock.json)과 Dockerfile/Compose에 있다. Lima VM 안의 Engine 설치는 공식 템플릿의 get.docker.com을 따르므로 새 VM 생성 시 Engine 버전은 다시 기록한다.

## 필요한 최소 검증

정상 빌드/기동을 한 뒤 새 실행 경계가 바뀔 때만 수행한다. 이 검증은 앱 중단·DB 중단·down/up을 실제 수행하므로 별도 개발 환경에서 실행한다. 검증 이름이 붙은 임시 행 2개만 넣고 정확히 그 행만 삭제하며 볼륨은 삭제하지 않는다.

```sh
# 기본 환경이 실행 중이면 먼저 보존 종료
scripts/dev-stack.sh down
FACTORY_COMPOSE_PROJECT=factory-foundation-check python3 scripts/verify-stack.py
```

별도 프로젝트의 새 볼륨에서 최초 초기화, 준비 상태, 수집 중단 격리, DB 장애 시 readiness/liveness 구분, 재기동 기록/Flyway 이력 보존을 한 시나리오로 확인한다. 이후 같은 이름으로 검증하면 그 볼륨을 재사용한다. 결과는 `.build-cache/stack-verification/stack-probe-…/result.json`과 commands.log에 남는다. 기본값은 끝에 컨테이너를 종료하며 `--keep-running`이면 기동 상태를 유지한다. 이번에는 기본 종료를 사용했다.

[작업 7 설명](<../docs/work-notes/작업 7. Compose와 실행 준비 상태.md>) · [작업 8 설명](<../docs/work-notes/작업 8. Python과 Vue 기본 앱.md>)

공식 기준: [Compose 기동 순서](https://docs.docker.com/compose/how-tos/startup-order/) · [Spring Actuator health](https://docs.spring.io/spring-boot/reference/actuator/endpoints.html) · [Lima Docker 템플릿](https://lima-vm.io/docs/templates/).

## S03 수집과 명시적 송신

`INGESTION_TCP_PORT`의 기본 호스트 포트는 9090이다. 수집 컨테이너는 0.0.0.0:9090에서 받고 호스트는 127.0.0.1만 공개한다. 입력 오류 로그는 `ingestion-diagnostics` 볼륨의 /var/log/factory/rejections.ndjson에 10MiB×3으로 보존한다. Python의 미확인 송신 목록은 메모리이며 이 볼륨에 저장하는 기능은 없다.

```sh
# 필요한 두 서비스만 코드 반영, 기존 DB/볼륨 보존
scripts/dev-stack.sh compose up -d --build --wait ingestion-service factory-simulator
# 이미 준비된 환경에서 새 run 1대의 실제 Python->TCP->DB 검증 후 자기 run만 정리
python3 scripts/verify-ingestion-source.py
```

S03에서 두 서비스 빌드/기동과 원본/ACK 39건의 실제 연결을 확인했다. 일반 Python 프로세스는 자동 생산/송신을 시작하지 않는다. S03 당시 수집된 outbox는 PENDING이었다. S05 이후는 자동 HTTP 전달로 처리되며 위 verify-ingestion-source.py도 현재의 두 DB/REST 검증으로 연결한다. 기존 Vue/샘플 GUI는 아직 공장 데이터 LIVE와 연결되지 않았다. [수집 안내](../services/ingestion-service/README.md) · [Python 송신 안내](../services/factory-simulator/README.md).

## S04 관제 코드 반영과 최소 확인

```sh
scripts/dev-stack.sh compose up -d --build --wait --no-deps operations-service
python3 scripts/verify-operations.py
```

관제 컨테이너만 다시 빌드하고 기존 DB/Flyway V1/볼륨을 유지한다. 새 검증 UUID의 기존 행0건을 확인한 뒤 모델 사건60건을 내부 HTTP로 반영해 DB 원본/해시·작업3/운송6/검사1·태그 HOLD·알람 확인/복구를 확인하고 자기 run만 정리한다. 실제 결과는 [최소 검증 안내](<../docs/validation/최소 검증 시나리오와 도구.md>)에 있다. 이는 S05 자동 outbox 전달이나 S06 GUI 연결을 대체한 검증이 아니다.

Compose는 관제의 INGESTION_DIAGNOSTIC_URL을 http://ingestion-service:8081로 전달한다. S05에서 수집 delivery-status 경로를 제공했다. 제공 실패/수집 미등록 실행의 진단 미확인은 계속 UNAVAILABLE/UNKNOWN으로 표현한다. 수집 프로세스 중단을 관제 기동 실패로 만들지 않는다. [관제 실행/조회 안내](../services/operations-service/README.md).

## S05 코드 반영과 실제 전달 복구

```sh
scripts/dev-stack.sh compose up -d --build --wait --no-deps ingestion-service
# 정상 검증; 서비스 중단 없음
python3 scripts/verify-delivery.py
# 별도 개발 환경에서 관제 중단/수집 재시작/관제 복구까지
python3 scripts/verify-delivery.py --with-restarts
```

수집 V2만 추가 적용하고 기존 V1·DB·볼륨을 유지한다. 수집의 OPERATIONS_BASE_URL은 http://operations-service:8082다. 양 서비스 사이에 기동 의존성을 추가하지 않았다. worker가 실행 중이어도 관제가 반영하지 못하면 보고서가 밀릴 수 있으므로 /readyz와 delivery-status를 구분한다.

이번에는 마지막 시나리오 한 번으로 Python TCP ACK60건→자동 HTTP→관제 DB60건·원본/해시 일치·태그 HOLD/FAIL·관제 REST LIVE→FINISHED를 확인했다. 관제 중단 중 뒤 보고서를 수집하고 수집기를 재시작한 뒤 같은 커서/대기/횟수로 복구했다. 관제는 정상 복원됐고 다른 서비스/DB/볼륨은 초기화하지 않았다.

helper는 생성한 새 UUID가 두 DB에 없음을 확인한 뒤 송신한다. 중단 옵션은 다른 실행의 미전달이 있으면 거절한다. 성공한 자기 실행만 두 DB에서 정리하고 실패한 실행은 보존한다. 종료 경로에서 잠시 중단한 관제를 복원한다. 상세 결과는 [검증 기록](<../docs/validation/최소 검증 시나리오와 도구.md>), 상태/격리 조회·명시적 재개는 [수집 안내](../services/ingestion-service/README.md)를 따른다. S05 당시 SSE/실제 Vue 연결은 후속이었으며 S06에서 최소 연결을 완료했다. 상시 생산과 성능 시험은 후속이다.


## S06 최소 실제 연결과 변경 반영

```sh
# 기존 DB/볼륨을 유지한 채 변경한 앱 이미지 반영
scripts/dev-stack.sh compose up -d --build --wait --no-deps operations-service factory-console factory-simulator
# 호스트 Python에서 새 실행 생성
INGESTION_TCP_HOST=127.0.0.1 INGESTION_TCP_PORT=9090 scripts/simulator.sh run --connected-demo
```

Vue http://127.0.0.1:5173에서 출력된 실제 run을 선택한다. Nginx의 같은 /api 경로가 관제로 연결되며 SSE는 buffering/cache를 끈다. 새 보고가 없거나 진단을 읽을 수 없으면 정상이라고 추정하지 않는다. 일반 Python health/heartbeat는 공장 생산이나 TCP 보고가 아니다. Docker의 명시적 시나리오 기록 기본 경로는 쓰기 가능한 /tmp이며 로컬 호스트 실행은 프로젝트 .build-cache다.

이번 실제 검증은 자기 helper가 만든 Python 프로세스만 잠시 SIGSTOP/SIGCONT했다. 기존 Spring/DB를 중단하거나 볼륨을 초기화하지 않았다. 최종 성공한 새 UUID만 두 DB에서 정리했고 실패한 시도는 진단 자료와 행을 보존했다. 현재5개 컨테이너의 준비 상태는 개발 환경의 상태이며 수백 대 성능 증거가 아니다. 전체 확인은 [S06 검증 기록](<../docs/validation/최소 검증 시나리오와 도구.md>)과 [Vue 안내](../services/factory-console/README.md)를 따른다.


## S07 실제 관제 기능 실행

Vue 지도/태그/품질/알람/이력까지 완료했고 S07 완료 당시 다음은 S08-01이었다. 변경한 화면/시뮬레이터만 `scripts/dev-stack.sh compose up -d --build --wait --no-deps factory-console factory-simulator`로 반영한다. 검증은 빌드/재배포가 끝난 뒤 시작한다. 기존 DB·볼륨·Java 서비스는 유지한다. `INGESTION_TCP_HOST=127.0.0.1 INGESTION_TCP_PORT=9090 scripts/simulator.sh run --connected-p0-demo`로 새 실제 실행을 만들고 화면에서 해당 runId를 선택한다. 실제 전체 경로는 `python3 scripts/verify-p0-console.py`이며 성공한 새 UUID만 정리한다. [Vue 사용법과 캡처](../services/factory-console/README.md).

## S08 장애·복구 통합 완료

S08-01~04에서 별도 PostgreSQL과 두 서버로 예약 취소/반환·목적 셀 정지 중 도착·확인/복구, TCP ACK 유실/재전송·12초 보고 단절, 양 서비스와 개별 DB·PostgreSQL 재시작을 확인했다. 최종 5대 실행 원본216건과 100대 실행 원본3,533건은 두 DB에서 순번·바이트·해시가 일치했다. 100대의 2,764 tick에서 단일 위치/용량을 확인하고 중간 전체 스냅샷28개와 최종 상태를 관제 API와 비교했다. 작업300/검사100/운송400·PASS80/FAIL20, 검사/운송 원본 각각10회 재전송의 실적 증가0·run 격리가 통과했다. 실제 Chrome의 SSE 단절/복구·태그 선택/마지막 값 보존은 별도 실행 증거를 명시해 재사용했다. 기존 Java 관련2개만 선택 실행했고 전체 테스트·새 의존성·DDL·운영 코드 변경은 없다. 기존 스택과 흰색/네이비/파란색 UI·개발 DB/볼륨을 유지했다. 논리 공정의 정확성 검증이며 S08 당시의 기능 정확성 기록이며 실제 성능은 이후 S09에서 측정했다.

[S08 결과/재실행](<../docs/development/S08 장애·복구 통합 검증.md>). 검증 전용 native PostgreSQL/Java를 사용하므로 기존 Compose를 중단하거나 볼륨을 삭제하지 않는다. 현재 S09까지 완료했다.

## S09 완료와 재실행

[실제 측정/P0 완료표](<../docs/development/S09 측정·완료 기록.md>) · [처음 실행/기존 데이터/복구/시연](<../docs/development/초기 실행·재실행·복구·시연.md>) · [새 실제 시연 캡처/단계 재생](<../docs/development/s09-demo/index.html>).

S09-01~04를 완료했습니다. 측정은 별도 네이티브 검증 DB/임의 loopback 포트를 사용하며 개발 Compose DB/볼륨은 유지했습니다. 정상25.63~25.72건/s·작은 화면 반영 p95 약98ms, 높은 입력 목표 미생성·업무 전달 지연을 구분합니다. SQL 병목이 확인되지 않아 새 index/DDL/의존성은 추가하지 않았습니다. 수집 Flyway1/2·관제1 그대로이며 같은 기존 data 재시작의 선택8개 표 지문이 일치했습니다. 일반 기동은 자동 생산하지 않습니다.
