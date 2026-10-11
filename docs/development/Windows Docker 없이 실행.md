# Windows에서 Docker 없이 실행하기

프로젝트 루트의 PowerShell에서 실행한다. 관리자 권한, Docker, WSL, 시스템 PATH 변경 없이 프로젝트 전용 도구를 `.build-cache/windows-tools`에 준비한다. Windows x64 기준이다.

## 더블클릭으로 실행

GitHub 전체 소스를 받은 뒤 [처음 실행 안내](../../WINDOWS-START.md)를 따른다. 최초 `01-prepare-windows.cmd` → `02-start-windows.cmd`, 다음부터 02번만 실행한다. 종료는 `03-stop-windows.cmd`, 상태 확인은 `04-status-windows.cmd`다. 압축파일 안에서 실행하지 않고 전체 해제한다. Git 설치나 `.git` 폴더는 필요하지 않다. 최신 소스와 이 파일들이 원격 브랜치에 포함되어야 한다.

아래 PowerShell 명령은 같은 절차의 수동 실행 방법이다.

## 최초 준비

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 setup
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 build
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 up
```

`setup`은 공식 배포 ZIP을 내려받아 SHA-256을 확인하고 풀며, 기존 `.env`는 유지한다. 고정 주소와 체크섬은 `scripts/windows-tools.json`에 있다. Node 24.21.0, Zulu JDK 21.0.12.1, PostgreSQL 17.11, Maven 3.10.0, Python 3.12.10을 사용한다. Python은 외부 패키지가 없는 현재 시뮬레이터를 위한 embeddable 배포판이며 pip/venv는 포함하지 않는다. 향후 Python 의존성을 추가하면 일반 Python 3.12와 가상환경으로 전환해야 한다.

`build`는 두 Java 서버 JAR과 Vue 화면을 빌드한다. Maven/npm 다운로드 캐시도 프로젝트 `.build-cache` 안에 둔다. `up`은 전용 DB, 관제 서버, 수집 서버, Vite 개발 화면 순으로 시작하고 HTTP 준비 상태를 기다린다. 화면 변경은 바로 반영된다. 첫 다운로드와 빌드는 인터넷 연결이 필요하다.

## 현재 시나리오 실행 · 2026-10-11

화면: **http://127.0.0.1:5173**

화면 상단 **시나리오**에서 **1대 · 정상 생산 / 3대 · 정상 생산 / 5대 · 장애 / 수동 복구** 중 선택하고 **시뮬레이션 시작**을 누른다. 기본 선택은 5대다. 새 run 등록 후 자동 연결된다. 모든 일반 시나리오는 PASS 패턴이며 5대는 첫 ASM-01 작업에 장애를 한 차례 주입한다. **장애 확인 → 현장 점검 시작 → 조치 완료 · 재가동**을 사용하고 2초 확인 후 작업을 재개한다. 자동 복구하지 않는다.

3D 공장과 2D 지도를 전환하고 AGV·AMR 선택으로 3인칭 추적을 사용한다. AGV는 전면 1인칭도 가능하다. ASM 부품 재고는 실제 키트 소비/AMR 배송으로 변한다. **중단**은 현재 실행기의 Python을 종료하며 다음 시작은 새 run이다.

이 버튼은 `windows-dev.ps1 up`이 띄운 Vite 개발 화면에서 제공된다. 정적 배포/Docker 화면에는 로컬 프로세스 실행 기능이 없다. 화면을 처음 수정한 뒤에는 개발 서버를 다시 시작해야 한다. 버튼 실행과 아래 터미널 실행을 동시에 사용하지 않는다. 개발 화면 서버를 종료하거나 Vite 설정 변경으로 재시작하면 버튼으로 실행한 시뮬레이터도 중단되므로 완료를 기다린다. 버튼 실행 로그는 `.build-cache/windows-dev/logs/web-simulator.log`에 남는다.

별도 PowerShell의 정상 CLI도 사용할 수 있다. 현재 3D 교통 규칙을 사용하려면 일반 demo 별칭 대신 simulator에 --traffic을 전달한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 simulator --connected-demo --traffic
```

화면에서 목록을 새로고침하고 **시뮬레이션 기록**의 시작 시각으로 실행을 선택한다. 출력된 `runId`로 찾으려면 **실행 ID로 직접 연결**을 펼쳐 ID를 입력하고 **관측 연결**을 누른다. 완료 후 GOOD/PASS, 실행 상태 FINISHED를 확인한다. 차체 3대 정상 생산은 다음 명령이다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-dev.ps1 simulator --connected-three-demo --traffic
```

아래 demo-p0는 과거 자동 검증 전용이다. 일반 5대 수동 시나리오는 웹 버튼을 사용한다. CLI 단독 실행은 Vite의 수동 명령 제어 연결을 만들지 않는다.

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

차체 5대·AGV 2대·AMR 1대다. ASM-01 작업 1초 후 위치 센서 불일치를 주입한다. 점검 대기와 현장 조치 중에는 남은 작업 시간이 보존된다. 조치 완료 후에만 재개하며 같은 작업의 부품을 중복 소비하지 않는다. 현재 5대 시나리오는 PASS 5/GOOD 5로 완료되도록 구성된다.

AGV는 빈 셀 직접 인계, 대기 필요 시 Bay 사용, Bay에서 셀로 재운반한다. 적재 전진·통로 예약/양보를 적용하고 모든 생산·출고가 끝난 뒤 외곽으로 최종 복귀한다. AMR은 후면 통로로 ASM별 키트를 보충하며 재고+보급 중 수량 및 남은 생산 수요를 반영한다. 정상 실행에서도 부품 구역을 표시한다. 1대는 초기 재고로 충분해 AMR이 대기할 수 있다.

**알람 확인**은 수동 조치 버튼과 다르다. 장애 조치 이력은 `.build-cache/connected-demo/<runId>/maintenance.json`에 보존한다. 과거 P0의 FULL_RESERVED 등 marker와 자동 4초 진행을 현재 수동 시나리오에 적용하지 않는다.

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

## 과거 Windows 확인 결과 · 2026-10-06

아래는 당시 2D/자동 P0 버전의 실측이다. 현재 3D·5대 수동 복구는 소스/스크립트 대조와 macOS 검증을 반영했으며 새 Windows에서 동일 검증을 재수행했다는 뜻이 아니다. [현재 검증 범위](<현재 기능과 검증 범위.md>)를 참고한다.

AGV 배차 개선 후 Python 테스트 24개와 콘솔 테스트 7개, Vue 빌드가 통과했다. 기본 설정의 3대 정상 생산 실행 `run-20261006-79e877515a9243aba2cf4895cc13fcd9`는 GOOD/PASS 3대, FINISHED, 전달 대기 0건으로 완료됐다. 모델의 완료 시간은 이전 3대 실행의 150,000ms에서 79,100ms로 줄었다. 부품·장애·복구 연결 검증은 별도 임시 설정(작업 200ms, 운송 1,000ms)으로 실행했으며 `run-20261006-bf9bc74501e240dc97058daef107f86c`의 다섯 관찰 단계와 GOOD 4대/HOLD 1대 완료를 확인했다. 기본 설정 파일은 유지했다. 정상 생산에서는 부품 구역이 숨겨지고, 부품 운송 실행은 완료 후 새로고침해도 AMR와 부품 구역이 표시됐다.

2026-10-06 Windows x64에서 최초 setup, 두 Java 서버 빌드, Vue 빌드, Python 설정 검사, DB 초기화와 Flyway 기동을 확인했다. 차체 1대 실제 연결 실행 `run-20261006-fa1bee7f259e4821868d3ff75ef281cf`는 FINISHED, GOOD/PASS로 완료됐다. 수집 원본 236건과 outbox 전달 236건, 관제 APPLIED 236건을 확인했고 전달 대기는 0건이었다. Chrome에서 실시간 공정 이동을 확인했으며 `down → up` 후에도 같은 완료 기록이 유지됐다. 이 확인은 최초 실행 연결 확인이며 전체 회귀·5대 시나리오·부하 테스트 통과를 의미하지 않는다. 로컬 검증 요약은 `.build-cache/windows-dev/verification.json`에 있다.
