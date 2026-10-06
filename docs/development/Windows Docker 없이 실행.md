# Windows에서 Docker 없이 실행하기

프로젝트 루트의 PowerShell에서 실행한다. 관리자 권한, Docker, WSL, 시스템 PATH 변경 없이 프로젝트 전용 도구를 `.build-cache/windows-tools`에 준비한다. Windows x64 기준이다.

## 최초 준비

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 setup
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 build
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 up
```

`setup`은 공식 배포 ZIP을 내려받아 SHA-256을 확인하고 풀며, 기존 `.env`는 유지한다. 고정 주소와 체크섬은 `scripts/windows-tools.json`에 있다. Node 24.21.0, Zulu JDK 21.0.12.1, PostgreSQL 17.11, Maven 3.10.0, Python 3.12.10을 사용한다. Python은 외부 패키지가 없는 현재 시뮬레이터를 위한 embeddable 배포판이며 pip/venv는 포함하지 않는다. 향후 Python 의존성을 추가하면 일반 Python 3.12와 가상환경으로 전환해야 한다.

`build`는 두 Java 서버 JAR과 Vue 화면을 빌드한다. Maven/npm 다운로드 캐시도 프로젝트 `.build-cache` 안에 둔다. `up`은 전용 DB, 관제 서버, 수집 서버, Vite 개발 화면 순으로 시작하고 HTTP 준비 상태를 기다린다. 화면 변경은 바로 반영된다. 첫 다운로드와 빌드는 인터넷 연결이 필요하다.

## 테스트

화면: **http://127.0.0.1:5173**

화면 상단의 **새로운 공장 실행**에서 시나리오를 선택하고 **새 시뮬레이션 시작**을 누르면 된다. 기본은 5대 버퍼·장애·복구·부품 운송이며, 1대 또는 3대 정상 생산을 선택할 수 있다. 3대 정상 생산은 세 차체를 정식 등록해 동일한 셀·버퍼·AGV 규칙으로 생산하며 최종 검사 세 건 모두 PASS, GOOD 도착으로 완료된다. 새 runId가 실제 관제 서버에 등록되면 화면이 자동으로 해당 실행에 연결된다. 버튼으로 시작한 시뮬레이션이 진행되는 동안 버튼을 비활성화해 중복 실행을 막으며, 브라우저를 새로고침해도 서버에서 진행 상태를 조회한다. 완료 후 다시 누르면 새 runId로 실행된다.

이 버튼은 `windows-dev.ps1 up`이 띄운 Vite 개발 화면에서 제공된다. 정적 배포/Docker 화면에는 로컬 프로세스 실행 기능이 없다. 화면을 처음 수정한 뒤에는 개발 서버를 다시 시작해야 한다. 버튼 실행과 아래 터미널 실행을 동시에 사용하지 않는다. 개발 화면 서버를 종료하거나 Vite 설정 변경으로 재시작하면 버튼으로 실행한 시뮬레이터도 중단되므로 완료를 기다린다. 버튼 실행 로그는 `.build-cache/windows-dev/logs/web-simulator.log`에 남는다.

별도 PowerShell에서 차체 1대 정상 시나리오를 실행한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 demo
```

화면에서 목록을 새로고침하고 **시뮬레이션 기록**의 시작 시각으로 실행을 선택한다. 출력된 `runId`로 찾으려면 **실행 ID로 직접 연결**을 펼쳐 ID를 입력하고 **관측 연결**을 누른다. 완료 후 GOOD/PASS, 실행 상태 FINISHED를 확인한다. 차체 3대 정상 생산은 다음 명령이다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 demo-three
```

버퍼·장애·부품 AMR·검사 5대 시나리오는 다음 명령이다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 demo-p0
```

Python 설정만 확인하거나 기존 CLI 옵션을 전달할 수도 있다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 simulator --check-config
```

일반 `up`은 생산을 시작하지 않는다. 시뮬레이터는 명시적으로 실행할 때만 생산한다. 실행 자료는 `.build-cache/connected-demo/<runId>`에 남는다.

## 재실행·종료·개발

### 5대 시나리오에서 확인할 것

5대는 차체 수다. 차량 구성은 차체 AGV 2대와 부품 AMR 1대다. 이 시연은 버퍼를 초과해 오류를 내는 대신 **예약을 포함한 용량 판단으로 신규 배차를 차단하고, 슬롯 반환 후 재개하는 보호 동작**을 보여 준다.

| 단계 | 확인할 상태 | 의미 |
|---|---|---|
| FULL_RESERVED | ASM-02 Bay W2/R1/A0/C3 | 도착 전 예약도 용량에 포함해 추가 배차 차단 |
| FULL_IN_TRANSIT | 같은 예약, 차체 위치 VEHICLE | 이미 예약한 운송은 만석 상태에서도 진행 |
| FULL_ARRIVED | W3/R0/A0, 앞 셀 BUFFER_FULL | 예약을 대기로 전환하며 슬롯 점유 유지 |
| CELL_DOWN | ASM-01 DOWN | 버퍼 만석과 별도로 의도적인 설비 장애 주입 |
| SLOT_RELEASED | 설비 복구, ASM-02 셀 진입 | 대기 차체의 슬롯 반환 후 운송 재평가 |
| FINISHED | GOOD 4대/PASS, HOLD 1대/FAIL | 지정 검사 결과와 모든 운송·귀환 완료 |

BUFFER_FULL은 정상적인 배차 차단 사유이고, DOWN은 설비 장애 상태다. 각 관찰 단계의 PAUSED는 장면을 보여 주기 위한 일시정지이며 오류가 아니다. 버튼/일반 CLI 시연에서는 각 단계가 4초 뒤 자동 진행한다. SLOT_RELEASED에서 반환 직후 A1이 생겨도 새 예약이 바로 잡히면 최종 화면은 R1/A0일 수 있다. 알람 확인 버튼은 확인 기록만 남기며 설비를 복구하거나 슬롯을 반환하지 않는다.

### AGV 배차와 지도 표시

AGV는 픽업 지점에 가장 가까운 빈 차량을 배차한다. 운송을 마친 차량과 빈 차로 복귀 중인 차량도 새 작업을 맡을 수 있으며, 현재 위치에서 다음 픽업으로 이동한다. 배차할 작업이 없으면 시작점으로 복귀한다. 목적지 Bay 슬롯이 없는 작업에는 배차하지 않는다.

정상 생산 화면에서는 사용하지 않는 AMR, 부품 보관·투입 위치와 부품 경로를 숨긴다. 부품 운송이 있는 5대 시나리오는 해당 구역을 표시하며, 운송 완료 후 실행을 다시 조회해도 표시를 유지한다.

### 서버 재실행과 종료

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 status
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 down
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 up
```

종료 전에 진행 중인 시뮬레이션을 완료한다. `down`은 이 스크립트가 기록한 서버 프로세스만 종료하고 PostgreSQL을 fast shutdown한다. Java 프로세스는 Windows Stop-Process로 종료하므로 개발용 강제 종료에 해당하며 Spring의 정상 종료 hook 완료를 보장하지 않는다. 이미 DB에 저장된 사건은 보존되며 재기동 시 전달이 재개된다. DB 파일과 실행 이력은 삭제하지 않는다. 재시작·재부팅 후에도 같은 `.env`와 데이터 폴더로 `up`하면 된다.

Java 코드를 변경하거나 pull로 서버 코드가 바뀌었으면 `down → build → up`한다. Vue 소스는 Vite가 바로 반영하며, 의존성 변경 시 `build` 후 다시 켠다. Python 변경은 다음 시뮬레이터 실행부터 반영된다. 별도 컴퓨터용 macOS/Linux 검증 스크립트는 이 Windows 환경에 자동으로 호환되는 것으로 가정하지 않는다.

| 구성 요소 | 주소 / 저장 위치 |
|---|---|
| Vue | http://127.0.0.1:5173 |
| 수집 HTTP / TCP | 127.0.0.1:8081 / 9090 |
| 관제 HTTP / SSE | http://127.0.0.1:8082 |
| 전용 PostgreSQL | 127.0.0.1:55432 |
| DB 파일 | `.build-cache/windows-dev/postgres-data` |
| 서버 로그 | `.build-cache/windows-dev/logs` |
| 로컬 암호 | 루트 `.env` (Git 제외) |

전체 구성은 Python 모델 → TCP 수집/원본 DB → outbox HTTP 전달 → 관제 DB/REST/SSE → Vue이다. DB는 `ingestion_db`와 `operations_db`로 나누며 각각 app/migrator 역할을 유지한다. Flyway가 서버 기동 시 기존 마이그레이션을 적용한다. 기존 Docker 구성은 계속 사용할 수 있으나 같은 HTTP/TCP 포트로 동시에 실행하지 않는다. Windows 실행 스크립트는 HTTP 8081/8082, TCP 9090, Vue 5173, DB 55432의 기본 포트를 사용한다.

오류가 나면 서버별 `.out.log`, `.err.log`, `postgres.log`를 확인한다. 데이터 폴더를 삭제하거나 `.env`를 재생성해서 해결하지 않는다. 실행 도구·DB·암호·빌드 결과는 Git 제외 대상이다. `.build-cache`를 정리하면 **이 구성의 DB 기록도 삭제**되므로 보존하거나 먼저 별도 백업한다.

## 이 컴퓨터에서 확인한 결과

AGV 배차 개선 후 Python 테스트 24개와 콘솔 테스트 7개, Vue 빌드가 통과했다. 기본 설정의 3대 정상 생산 실행 `run-20261006-79e877515a9243aba2cf4895cc13fcd9`는 GOOD/PASS 3대, FINISHED, 전달 대기 0건으로 완료됐다. 모델의 완료 시간은 이전 3대 실행의 150,000ms에서 79,100ms로 줄었다. 부품·장애·복구 연결 검증은 별도 임시 설정(작업 200ms, 운송 1,000ms)으로 실행했으며 `run-20261006-bf9bc74501e240dc97058daef107f86c`의 다섯 관찰 단계와 GOOD 4대/HOLD 1대 완료를 확인했다. 기본 설정 파일은 유지했다. 정상 생산에서는 부품 구역이 숨겨지고, 부품 운송 실행은 완료 후 새로고침해도 AMR와 부품 구역이 표시됐다.

2026-10-06 Windows x64에서 최초 setup, 두 Java 서버 빌드, Vue 빌드, Python 설정 검사, DB 초기화와 Flyway 기동을 확인했다. 차체 1대 실제 연결 실행 `run-20261006-fa1bee7f259e4821868d3ff75ef281cf`는 FINISHED, GOOD/PASS로 완료됐다. 수집 원본 236건과 outbox 전달 236건, 관제 APPLIED 236건을 확인했고 전달 대기는 0건이었다. Chrome에서 실시간 공정 이동을 확인했으며 `down → up` 후에도 같은 완료 기록이 유지됐다. 이 확인은 최초 실행 연결 확인이며 전체 회귀·5대 시나리오·부하 테스트 통과를 의미하지 않는다. 로컬 검증 요약은 `.build-cache/windows-dev/verification.json`에 있다.
