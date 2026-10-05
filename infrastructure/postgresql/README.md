# PostgreSQL DB·계정·마이그레이션

> S01-02 · PostgreSQL **17.11** · Flyway **12.4.0**(Boot 4.1.1 관리)  
> 수집 DB 4개 + 관제 DB 13개 업무 표와 각각의 Flyway 이력 표. Compose 실행은 S01-03에서 준비했다. [전체 실행 안내](../README.md)를 따른다.

## DB와 계정의 경계

| DB | 일반 앱 계정 | Flyway/DB 소유 계정 | 연결 허용 |
|---|---|---|---|
| ingestion_db | ingestion_app | ingestion_migrator | 수집 계정 두 개만 |
| operations_db | operations_app | operations_migrator | 관제 계정 두 개만 |

네 계정은 모두 LOGIN이지만 superuser/DB 생성/역할 생성/복제/BYPASSRLS 권한이 없다. 앱은 자기 public 스키마의 SELECT/INSERT/UPDATE/DELETE와 필요한 시퀀스/함수만 사용한다. CREATE·DROP·ALTER·TRUNCATE 권한은 주지 않는다. Flyway 계정은 자기 DB/객체를 소유해 구조를 변경한다. 다른 DB와 postgres/template DB의 PUBLIC CONNECT도 제거한다. 권한 없는 접속은 비밀번호 확인을 통과해도 SQLSTATE 42501로 거절된다.

[init-databases.psql](init-databases.psql)은 **새로운 전용 프로젝트 PostgreSQL 인스턴스에서 관리자 계정으로 한 번** 실행하는 초기 준비다. 기존 프로젝트 역할/DB가 하나라도 있으면 변경 전에 오류로 중단한다. DROP·재생성·비밀번호 덮어쓰기를 하지 않는다. 역할 생성은 한 트랜잭션, CREATE DATABASE는 PostgreSQL 규칙상 그 밖에서 수행한다. 중간 실패가 나면 생성된 역할/DB를 확인하고 원인을 고쳐야 하며 자동 초기화하지 않는다. 다른 업무와 공유하는 인스턴스에 적용하는 스크립트가 아니다.

[database.env.example](database.env.example)은 이름/URL 예시이며 실제 암호가 아니다. 네 PASSWORD를 다른 값으로 정해 환경 변수로 전달한다. 관리자 접속은 PGHOST/PGPORT/PGUSER/PGPASSWORD로 설정하고, `FACTORY_PSQL`로 psql 경로를 지정할 수 있다.

```sh
scripts/init-databases.sh
```

암호는 psql 환경 변수→인용한 SQL 값으로 전달하며 명령줄 인자에 넣지 않는다. `--no-psqlrc`로 사용자 개인 psql 시작 파일도 실행하지 않는다. 운영 계정/암호 교체 도구는 이후 운영 작업이며 이 초기 준비로 기존 DB를 다시 만들지 않는다.

## 서비스별 Flyway

- [수집 V1](../../services/ingestion-service/src/main/resources/db/migration/V1__ingestion_storage.sql): raw_event, event_outbox, delivery_stream.
- [수집 V2](../../services/ingestion-service/src/main/resources/db/migration/V2__delivery_attempts_and_resumption_audit.sql): outbox 누적 시도/최근 시도 시각, delivery_action 명시적 재개 기록. V1 변경 없음.
- [관제 V1](../../services/operations-service/src/main/resources/db/migration/V1__operations_storage.sql): simulation_run, equipment, factory_buffer, vehicle, body, processed_event, event_projection, factory_snapshot, inspection_result, operation_history, transport_history, alarm, alarm_note.

각 앱은 자기 DB URL을 사용하고, DataSource는 *_DB_USERNAME/PASSWORD, Flyway는 *_MIGRATION_USERNAME/PASSWORD를 사용한다. 앱 계정으로 마이그레이션하지 않는다. 두 연결은 같은 서비스 DB를 대상으로 한다. 일반 실행의 필수 설정은 URL과 두 계정의 사용자/암호 **5개**다. bootstrap은 이 연결들을 제외한다.

Flyway history에는 적용 버전과 체크섬이 남는다. 앱 계정은 이 표를 조회할 수 있지만 INSERT/UPDATE/DELETE는 못 한다. 적용된 V1을 고치는 대신 이후 변경은 V2/V3로 추가한다. clean은 꺼져 있고 재기동은 누락된 버전만 적용한다. 마이그레이션에는 데모 차체/실적·DROP·TRUNCATE를 넣지 않았다.

사건의 ID/순번 고유성, 원문 SHA-256, 원문 크기, 태그 1:1, run 범위 참조, 검사 중복·PASS/FAIL, 슬롯 구성 용량, 활성 운송/알람 중복을 DB의 기본 제약으로 준비했다. Python 모델·JSON 상세 규격·예약/차체 보존 전체 검증·과거 값 덮어쓰기 방지는 S02~S05의 업무 코드에서 구현/검증한다. SQL 적용 성공을 그 기능의 구현 완료로 쓰지 않는다.

processed_event와 event_projection은 RUN_STARTED 거절도 남길 수 있게 simulation_run 외래키를 요구하지 않는다. 정상 메타데이터·fact·현재 snapshot의 참조는 자기 DB 안에서만 연결한다. body/설비/차량/Bay ID는 run별로 구분한다. operation_history의 entered_at은 초기 snapshot으로 소개한 작업에서 null일 수 있으며 알 수 없는 실제 시작 시각을 만들지 않는다.

페이지 조회용 record_ordinal은 simulation_run/event_projection/alarm에서 한 내부 시퀀스와 트랜잭션 advisory lock을 사용해 배정한다. 번호를 받은 트랜잭션이 끝날 때까지 다음 배정을 기다리므로 늦은 커밋이 이미 정한 fence에 끼어들지 않는다. P0는 한 트랜잭션에서 한 run만 쓰고 run 잠금→ordinal 잠금 순서로 처리한다. sourceSeq/전달 커서를 이 번호로 대신하지 않는다. 관제 쓰기 코드·cursor API는 S04에서 구현했다. 수집 전달 커서/완료 저장과 명시적 재개 기록은 S05에서 구현했다.

## 실제 DB 최소 검증

S01-02 당시 Docker/기존 PostgreSQL이 없어 공식 17.11 소스를 임시 경로에 빌드했다. S01-03에서는 별도의 실제 Compose PostgreSQL 환경도 검증했다. 시스템 PostgreSQL·Homebrew 설정·전역 서비스는 설치/변경하지 않았다. 로컬 검증 바이너리는 ICU/readline을 제외한 빌드이고 C locale/UTF8을 사용한다. 이 빌드가 향후 Compose 이미지와 동일한 운영 환경이라고 주장하지 않는다. 공식 소스 SHA-256은 다음과 같다.

```text
5367f6fb2ec97efe1eb2e0c7926bb33438e51b0bd3a9733b88498056a7dc9a7e
```

필요한 경우 curl/Python/컴파일러/make 등 PostgreSQL 빌드 도구가 있는 macOS/Linux에서 다음 보조 명령으로 로컬 검증 도구를 준비할 수 있다. 이미 17.11 도구가 있으면 FACTORY_PG_BIN으로 지정한다. 보조 스크립트는 이번에 사용한 다운로드/체크섬/configure/make/install 명령을 정리한 것이며, 스크립트 전체를 다시 실행해 중복 빌드하지 않았다.

```sh
scripts/prepare-postgresql.sh
```

검증 전에 S01-01의 Maven 의존성 캐시가 준비되어 있어야 한다. 이 검증은 Maven --offline으로 실행한다.

```sh
python3 scripts/verify-databases.py
```

이 명령은 **새 검증용 클러스터**를 만들고 localhost의 임시 포트에서 시작한다. 역할/DB 초기화→앱별 DatabaseMigrationTests 1개→기존 초기화 거절→표 소유 개수 확인 후 해당 서버만 종료한다. 인증은 TCP SCRAM-SHA-256이고, 관리자만 0700 임시 Unix 소켓에서 trust로 접속한다. 데이터 경로는 workspace, Unix 소켓은 macOS 길이 제한을 피한 짧은 /tmp 경로다.

테스트는 정상 Flyway 마이그레이션/자기 DB 쓰기, 재실행 0건과 확인용 행 유지, 다른 서비스 DB 및 postgres 접속 거절, 앱 CREATE 거절·Flyway history 변경 권한 없음까지 한 사례로 묶었다. getter나 메모리 DB 테스트로 대체하지 않았다. 테스트용 행만 삭제하고 DB 구조/이력/클러스터는 보존한다.

테스트 클래스는 FACTORY_DATABASE_TESTS=true일 때만 실행하며 일반 빌드에서는 DB 환경이 없다고 실패하지 않고 건너뛴다. 기존 bootstrap 기동 테스트도 이번 DB 검증에서 반복하지 않았다. 외부/운영 DB에 테스트 플래그를 켜지 않고 제공한 새 클러스터 검증 명령을 사용한다.

로그/result.json과 자동 생성한 서로 다른 암호는 `.build-cache/database-verification/<실행번호>/`에 남긴다. 암호 파일은 0600·상위 디렉토리는 0700이며 출력/버전 관리하지 않는다. 데이터는 자동 삭제하지 않는다. 종료 여부는 result.json의 stoppedOnExit와 stop.log로 확인한다. 검증 후 상시 DB가 켜져 있다는 뜻은 아니다.

## 공식 근거

- [PostgreSQL 17.11 소스 배포](https://ftp.postgresql.org/pub/source/v17.11/): 버전/체크섬.
- [PostgreSQL GRANT](https://www.postgresql.org/docs/17/sql-grant.html): DB CONNECT와 스키마·표 권한.
- [기본 권한](https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html): 마이그레이션 계정이 만드는 새 객체 권한.
- [pg_hba.conf](https://www.postgresql.org/docs/17/auth-pg-hba-conf.html): 접속 인증 규칙. 인증과 DB 권한은 별도 확인.

[작업 6 해설](<../../docs/work-notes/작업 6. 두 DB와 서비스별 저장 구조.md>) · [단계별 계획](<../../가상 제조공장 실시간 통합 관제 시스템 - 단계별 개발 계획.md>)

## S05 추가 구조와 최소 확인

기존 수집 V1의 attempt_count는 현재 자동 시도 묶음(0~20)이다. V2는 기존 횟수로 total_attempt_count를 채우고 이후 명시적 재개에도 누적 횟수/last_attempt_at을 유지한다. 새 delivery_action은 실행·송신원·현재 순번·RESUME·이전 보류 상태·운영자·이유·시각을 남긴다. 현재 업무 표는 수집4/관제13=총17개, 마이그레이션은 수집2/관제1이다. V1 checksum과 데이터는 유지하며 자동 데이터 정리나 Flyway clean은 하지 않는다.

`python3 scripts/verify-databases.py --suite delivery`로 새 PostgreSQL17.11 클러스터의 두 DB/분리된 앱 계정과 실제 관제 프로세스에서 S05 8개가 통과했다. 원본·전달/업무 저장·실제 제약 rollback·관제 DB 접속 차단/복구·재개 audit를 확인했다. V2는 기존 Compose 수집 이미지 기동에도 정상 추가 적용됐다. 기존 S01 전체 검증은 반복하지 않았다. helper 종료 시 자기 프로세스/검증 클러스터만 정지했다. [S05 결과](<../../docs/validation/최소 검증 시나리오와 도구.md>).


S06은 새 DDL 없이 기존 수집V1·V2/관제V1을 사용했다. `verify-databases.py --suite stream`은 별도의 임시 PostgreSQL17.11과 실제 HTTP로 SSE 경계3개만 확인하며 기존 Compose DB/볼륨을 바꾸지 않는다. [S06 증거와 데이터 보존](<../../docs/validation/최소 검증 시나리오와 도구.md>)을 참고한다.

## S09 완료와 재실행

[실제 측정/P0 완료표](<../../docs/development/S09 측정·완료 기록.md>) · [처음 실행/기존 데이터/복구/시연](<../../docs/development/초기 실행·재실행·복구·시연.md>) · [새 실제 시연 캡처/단계 재생](<../../docs/development/s09-demo/index.html>).

S09-01~04를 완료했습니다. 측정은 별도 네이티브 검증 DB/임의 loopback 포트를 사용하며 개발 Compose DB/볼륨은 유지했습니다. 정상25.63~25.72건/s·작은 화면 반영 p95 약98ms, 높은 입력 목표 미생성·업무 전달 지연을 구분합니다. SQL 병목이 확인되지 않아 새 index/DDL/의존성은 추가하지 않았습니다. 수집 Flyway1/2·관제1 그대로이며 같은 기존 data 재시작의 선택8개 표 지문이 일치했습니다. 일반 기동은 자동 생산하지 않습니다.
