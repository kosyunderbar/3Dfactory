# 가상 제조공장 실시간 통합 관제 시스템

**Windows에서 처음 실행한다면:** [WINDOWS-START.md](WINDOWS-START.md)를 읽고 `01-prepare-windows.cmd` → `02-start-windows.cmd`를 더블클릭하세요. GitHub 소스 전체가 필요하며 최초 준비에는 인터넷이 필요합니다.

현대오토에버 OT 시스템 개발 및 운영 직무 지원을 위한 프로젝트입니다. 독립 셀·AGV/AMR의 실제 데이터 관측, 스마트태그·버퍼·품질·알람을 Spring/Python/Vue의 소규모 MSA로 구현했습니다.

저장소: [kosyunderbar/smartfactorysimul](https://github.com/kosyunderbar/smartfactorysimul). 다른 컴퓨터에서 시작할 때는 [clone·실행·개발 안내](<가상 제조공장 실시간 통합 관제 시스템 - 다른 컴퓨터 실행·개발 안내.md>)를 따릅니다.

현재 **S00~S09 P0 + 작업 59까지** 구현했습니다. 상세 Three.js 공장, AGV·AMR 3인칭 추적과 AGV 전면 시점, 통로 예약/양보·적재 전진·최종 외곽 복귀, ASM 부품 재고와 AMR 실제 보급, 사용자 점검·조치 기반 수동 복구를 제공합니다.

[작업 61](<docs/work-notes/작업 61. 3D 관측 재생 끊김과 추적 카메라 부하 개선.md>)에서 관측 버퍼 기반 3D 연속 재생과 추적 카메라 부하를 개선했습니다.

일반 시나리오는 **1대 정상 / 3대 정상 / 5대 장애·수동 복구**입니다. 5대는 차체 수이며 차량은 AGV 2대·AMR 1대입니다. 실제 사용 방법은 [기능과 시연](<가상 제조공장 실시간 통합 관제 시스템 - 기능 설명 및 시연 시나리오.md>), 구현 한계와 증거는 [현재 기능과 검증 범위](<docs/development/현재 기능과 검증 범위.md>)를 참고합니다.

S08의 차체 100대와 S09의 원본 151,073건 대조·약 98ms 조건부 화면 측정은 과거 버전의 검증 기록입니다. 최신 3D 성능이나 차량 100대 제어 성과로 해석하지 않습니다.

[S07-01 설명](<docs/work-notes/작업 29. S07-01 실제 공장 SVG 지도와 차량·슬롯.md>) · [S07-02 설명](<docs/work-notes/작업 30. S07-02 스마트태그 검색과 대상별 상세·이력.md>) · [S07-03 설명](<docs/work-notes/작업 31. S07-03 품질 차트와 알람 확인·기록 조회.md>) · [S07-04 설명](<docs/work-notes/작업 32. S07-04 선택·조회 순서와 모바일·키보드 접근.md>)

## 문서와 화면

- [현재 기능과 검증 범위](<docs/development/현재 기능과 검증 범위.md>): 작업 59까지의 구현, 실제 연결/오프라인 검증과 남은 범위.
- [작업 60 — 문서 갱신](<docs/work-notes/작업 60. 현재 3D·AMR·수동 복구 기준 문서 갱신.md>): 기획·해설·실행·시연·포트폴리오를 현재 기준으로 정리.
- [3D 개발 계획](<가상 제조공장 실시간 통합 관제 시스템 - 3D 관제 화면 개발 계획.md>): 초기 계획과 현재 완료 판정.

2026-10-11 현재 사용 안내는 3D·AMR 실제 공급·5대 수동 복구 기준입니다. 작업 42의 2D/자동 P0 결과는 당시 이력으로 보존합니다.

- [기획서](<가상 제조공장 실시간 통합 관제 시스템 - 기획서.md>): 목적, 요구사항, 시스템 설계와 검증 계획.
- [해설집](<가상 제조공장 실시간 통합 관제 시스템 - 해설집.md>): 처음 읽는 사람을 위한 동작 설명, 사례, 용어와 예상 질문.
- [기능 설명 및 시연 시나리오](<가상 제조공장 실시간 통합 관제 시스템 - 기능 설명 및 시연 시나리오.md>): 관람자용 기능 설명, 약 10분 발표 멘트·화면 조작·단계별 진행 명령, 예상 질문과 문제 대처.
- [이력서·포트폴리오 활용 마스터](<가상 제조공장 실시간 통합 관제 시스템 - 이력서·포트폴리오 활용 마스터.md>): 제조 SW 직무별 강조점, 이력서 문구, 개인 기여·AI 활용, 면접 사례와 검증 근거.
- [다른 컴퓨터 실행·개발 안내](<가상 제조공장 실시간 통합 관제 시스템 - 다른 컴퓨터 실행·개발 안내.md>): clone 후 최초 실행, 데이터 보존하며 pull·재빌드, OS별 준비, Vue·Python·Java 개발과 문제 해결.
- [작업 41. 지도 겹침과 좁은 화면 배치 수정](<docs/work-notes/작업 41. 공장 지도 겹침과 좁은 화면 배치 수정.md>): 같은 위치의 차량 분리, 차체 구역별 대수·번호, 보고 위치 연결선과 최소 확인.
- [단계별 개발 계획](<가상 제조공장 실시간 통합 관제 시스템 - 단계별 개발 계획.md>): 소규모 MSA 구성, S00~S09·작업 ID, 단계별 테스트와 완료 기준.
- [작업 1. 서비스 책임과 데이터 소유권](<docs/work-notes/작업 1. 서비스 책임과 데이터 소유권.md>): 처음 읽는 사람을 위한 프로그램별 역할, 차체 이동 사례와 이번 작업 결과.
- [작업 2. 식별자와 사건 데이터 규격](<docs/work-notes/작업 2. 식별자와 사건 데이터 규격.md>): 번호·시각·보고서 양식의 역할과 예약→도착→반환 예제.
- [작업 3. 저장 확인과 서비스 간 전달](<docs/work-notes/작업 3. 저장 확인과 서비스 간 전달.md>): 두 답장과 응답 유실·재시도·격리, 차체 Bay와 보고서 대기의 차이.
- [작업 4. 화면 조회와 실시간 상태 전달](<docs/work-notes/작업 4. 화면 조회와 실시간 상태 전달.md>): REST/SSE, 마지막 확인값·신선도·반영 지연과 최소 검증 설명.
- [작업 5. 두 Spring 앱의 실행 기반](<docs/work-notes/작업 5. 두 Spring 앱의 실행 기반.md>): Java·Spring·Maven의 역할, 실제 빌드/기동 결과와 다음 DB 작업.
- [작업 6. 두 DB와 서비스별 저장 구조](<docs/work-notes/작업 6. 두 DB와 서비스별 저장 구조.md>): 계정·표·Flyway의 역할과 실제 권한/마이그레이션 결과.
- [PostgreSQL DB 실행 안내](infrastructure/postgresql/README.md): 두 DB·4개 제한 계정·독립 마이그레이션과 최소 검증 명령.
- [Spring 서비스 실행 안내](services/README.md): 수집/관제 앱의 독립 빌드와 bootstrap 기동 방법.
- [실행 버전과 빌드 기준](<docs/development/실행 버전과 빌드 기준.md>): 고정한 Spring Boot/Maven/Wrapper와 실제 JDK·의존성 버전.
- [v1 화면 계약](contracts/v1/monitoring.md): 현재 값·이력·품질·진단·SSE 규칙. 자료 확인: `python3 scripts/check_monitoring_examples.py`.
- [최소 검증 시나리오와 도구](<docs/validation/최소 검증 시나리오와 도구.md>): 변경한 경계에서 필요한 사례만 수행하는 기준.
- [ADR-001 서비스 책임과 데이터 소유권](<docs/decisions/ADR-001-서비스 책임과 데이터 소유권.md>): 첫 작업에서 확정한 설계와 데이터 관리 책임.
- [v1 사건 계약](contracts/v1/events.md): 사건 17종의 필드 규격과 JSON/NDJSON 예제. 예제 확인: `python3 scripts/check_contract_examples.py`.
- [v1 전달 계약](contracts/v1/delivery.md): TCP ACK·내부 REST·순서·재시도·상한·버전 규칙. 자료 확인: `python3 scripts/check_delivery_examples.py`.
- [GUI 실행 안내](factory-gui/README.md): 메인 화면 실행 방법과 데모 시나리오.
- [GUI 시작 파일](factory-gui/index.html): 브라우저로 열어 디자인과 상호작용 확인.
- [현재 흰색·네이비 샘플 캡처](factory-gui/preview-white-blue.jpg).

- [작업 7. Compose와 실행 준비 상태](<docs/work-notes/작업 7. Compose와 실행 준비 상태.md>): 함께 기동/보존 종료, 서버 생존과 DB 준비의 차이, 실제 장애/복구 검증.
- [작업 8. Python과 Vue 기본 앱](<docs/work-notes/작업 8. Python과 Vue 기본 앱.md>): Python·Vue·Vite의 역할, 실제 시작 화면과 최소 검증.
- [전체 실행 안내](infrastructure/README.md): scripts/dev-stack.sh, 환경 변수·로그·서비스별 종료·로컬 Engine.
- [Python 실행 안내](services/factory-simulator/README.md) · [Vue 실행 안내](services/factory-console/README.md).

- [UI 색상 기준](<docs/development/UI 색상 기준.md>): 흰색 바탕·네이비 글씨·파란색 강조의 공통 기준.
- [작업 9. 흰색과 네이비 UI 색상](<docs/work-notes/작업 9. 흰색과 네이비 UI 색상.md>): 두 GUI의 색상 변경과 최소 확인 결과.

- [작업 10. 공장 설정과 차체·태그 등록](<docs/work-notes/작업 10. 공장 설정과 차체·태그 등록.md>): 실행별 등록부·유일한 현재 위치·서버 없는 모델 확인.

- [작업 11 설명](<docs/work-notes/작업 11. 셀 작업과 최종 검사.md>): 작업 시간·검사 결과·완료 후 셀 내 대기와 최소 검증.

- [작업 12 설명](<docs/work-notes/작업 12. 슬롯 예약과 AGV 배차.md>): 대기+예약의 만석 기준·AGV 동시 확보·완료 차체 보유.

- [작업 13 설명](<docs/work-notes/작업 13. AGV 운송과 버퍼 슬롯 반환.md>): 모델 운송·Bay 인계·슬롯 반환과 재배차.

- [작업 14 설명](<docs/work-notes/작업 14. 취소와 장애 복구 및 공장 모델 검증.md>): 취소/반복 처리·설비 고장 복구·부품 운송·100대 보존/사건 검증.


- [S03-01 설명](<docs/work-notes/작업 15. S03-01 TCP 입력 조립과 수신 제한.md>): TCP 조립·프레임/연결/입력 큐 제한.
- [S03-02 설명](<docs/work-notes/작업 16. S03-02 사건 검증과 중복 구분.md>): 사건 양식/번호·같은 원본과 충돌의 구분.
- [S03-03 설명](<docs/work-notes/작업 17. S03-03 원본과 전달 대기 저장 및 ACK.md>): 원본/outbox 동시 저장과 커밋 후 답장.
- [S03-04 설명](<docs/work-notes/작업 18. S03-04 Python ACK 처리와 제한된 재전송.md>): 미확인 원본·ACK·제한 재송신과 공장 정지.

- [S04-01 설명](<docs/work-notes/작업 19. S04-01 내부 사건 수신과 업무 처리 기록.md>): 내부 API·업무 검증·COMMIT/rollback·영속 중복 처리.
- [S04-02 설명](<docs/work-notes/작업 20. S04-02 차체·태그와 업무 이력 및 최신 상태.md>): 차체/태그·작업/운송/검사 사실·최신 스냅샷과 과거 상태 보존.
- [S04-03 설명](<docs/work-notes/작업 21. S04-03 관제 조회 API와 검사 집계.md>): REST·SQL·DTO, 100/20 검사 집계와 조회 페이지 경계.
- [S04-04 설명](<docs/work-notes/작업 22. S04-04 데이터 신선도와 알람 확인·복구.md>): 신선도·진단 실패·알람 확인/복구·후속 연결 구분.
- [관제 실행/조회 안내](services/operations-service/README.md): 구현된 API와 S04 최소 검증.

## 디렉토리 구조

```text
가상 제조공장 실시간 통합 관제 시스템/
├── README.md
├── 가상 제조공장 실시간 통합 관제 시스템 - 기획서.md
├── 가상 제조공장 실시간 통합 관제 시스템 - 해설집.md
├── 가상 제조공장 실시간 통합 관제 시스템 - 기능 설명 및 시연 시나리오.md
├── 가상 제조공장 실시간 통합 관제 시스템 - 이력서·포트폴리오 활용 마스터.md
├── 가상 제조공장 실시간 통합 관제 시스템 - 다른 컴퓨터 실행·개발 안내.md
├── 가상 제조공장 실시간 통합 관제 시스템 - 단계별 개발 계획.md
├── contracts/v1/
│   ├── events.md
│   ├── delivery.md
│   ├── delivery-policy.json
│   ├── monitoring.md
│   ├── monitoring-policy.json
│   └── examples/
│       ├── event-catalog.json
│       ├── buffer-lifecycle.ndjson
│       ├── delivery-examples.json
│       ├── monitoring-examples.json
│       └── factory-snapshot.sse
├── compose.yaml                 # PostgreSQL + 네 앱 기동/health/로그/볼륨
├── infrastructure/postgresql/  # DB/계정 준비·환경 변수 예시·실행 안내
├── services/
│   ├── README.md
│   ├── ingestion-service/      # 독립 pom.xml·Wrapper·main·설정·테스트
│   ├── operations-service/     # 독립 pom.xml·Wrapper·main·설정·테스트
│   ├── factory-simulator/      # Python 공장 설정·차체/태그·단일 위치 기초·unittest
│   └── factory-console/        # 실제 Vue/JavaScript/Vite 앱·npm 잠금 파일
├── scripts/
│   ├── check_contract_examples.py
│   ├── check_delivery_examples.py
│   ├── check_monitoring_examples.py
│   ├── service-maven.sh
│   ├── init-databases.sh
│   ├── prepare-postgresql.sh
│   ├── verify-connected-console.py # 최소 실제 전달/프록시 SSE 검증
│   ├── verify-databases.py
│   ├── dev-stack.sh             # 전체 기동·종료·로그
│   ├── verify-stack.py          # 실제 Compose 실행 경계 검증
│   ├── prepare-dev-tools.py     # 선택적인 로컬 도구 준비
│   ├── local-docker.sh          # 선택적인 검증용 Engine
│   ├── simulator.sh
│   └── console.sh
├── docs/
│   ├── decisions/
│   │   └── ADR-001-서비스 책임과 데이터 소유권.md
│   ├── development/
│   │   └── 실행 버전과 빌드 기준.md
│   ├── validation/
│   │   └── 최소 검증 시나리오와 도구.md
│   └── work-notes/
│       ├── 작업 1. 서비스 책임과 데이터 소유권.md
│       ├── 작업 2. 식별자와 사건 데이터 규격.md
│       ├── 작업 3. 저장 확인과 서비스 간 전달.md
│       ├── 작업 4. 화면 조회와 실시간 상태 전달.md
│       ├── 작업 5. 두 Spring 앱의 실행 기반.md
│       ├── 작업 6. 두 DB와 서비스별 저장 구조.md
│       ├── 작업 7. Compose와 실행 준비 상태.md
│       └── 작업 8. Python과 Vue 기본 앱.md
└── factory-gui/
    ├── README.md
    ├── index.html
    ├── styles.css
    ├── model.js
    ├── app.js
    ├── verify-model.js
    ├── preview-desktop.png
    ├── preview-tag.png
    ├── preview-buffer.png
    ├── preview-buffer-arrival.png
    └── preview-buffer-resume.png
```

GUI v0.2는 독립 작업 셀, 차체 AGV/부품 AMR, 가상 스마트태그 상세 창과 예약을 포함한 버퍼 배출 차단을 보여 주는 브라우저 프로토타입입니다. **버퍼 만석** 시나리오에서 차량 도착과 셀 진입을 단계별로 확인할 수 있습니다. 이 샘플은 브라우저 안에서만 동작합니다. 별도의 실제 Vue 앱은 S06에서 Python·서버·DB·SSE를 연결했고 S07에서 전체 관제 화면으로 확장했습니다. 기획서의 기술 스택을 유지합니다.

본 시스템은 수집·관제 Spring 서비스를 분리하는 소규모 MSA입니다. **테스트는 꼭 필요한 것만 수행**하며 작업별 설명 파일을 작성합니다. **S00~S09 P0 단계 완료**이며 실제 성능 목표의 달성/미검증은 S09 기록을 따릅니다. S06의 실제 최소 연결에 이어 S07에서 지도·태그 검색/상세·이력·품질 차트·알람 확인/복구 관측·접근을 연결했습니다. [S07 실제 Vue 안내](services/factory-console/README.md)를 따릅니다.

- [작업26/S06-01: Python 최소 시나리오](<docs/work-notes/작업 26. S06-01 Python 최소 시나리오와 실제 전달.md>)
- [작업27/S06-02: REST/SSE 전체 상태](<docs/work-notes/작업 27. S06-02 REST와 SSE 전체 상태 연결.md>)
- [작업28/S06-03: Vue 셀·태그 상세](<docs/work-notes/작업 28. S06-03 Vue 셀 관측과 차체·태그 상세.md>)

## 현재 3D·수동 복구 시연

서버/DB 준비 후 호스트 Python 3.12 가상환경과 Node 24를 사용합니다. 정적 Docker 5173은 관측용이고, 로컬 Vite 5174에서 실행·중단·수동 조치 버튼을 사용합니다.

```sh
# 최초 1회: Python 3.12 및 Node 24 준비 후
sh scripts/simulator.sh setup
sh scripts/console.sh install
FACTORY_SIMULATOR_PYTHON="$PWD/.build-cache/simulator-venv/bin/python" sh scripts/console.sh dev --port 5174
```

http://127.0.0.1:5174 에서 5대 장애 시나리오를 시작하고 **현장 점검 시작 → 조치 완료 · 재가동**으로 복구합니다. Windows 네이티브는 [전용 안내](<docs/development/Windows Docker 없이 실행.md>)의 `up`이 Vite 5173과 Python 경로를 준비합니다. 버튼 실행기는 기본 수집 TCP 9090을 사용합니다. Vite 종료/재시작은 관리 중인 Python도 중단하므로 실행 중 설정을 바꾸지 않습니다.

![AGV 상세 추적](docs/development/3d-review/third-person-agv-loaded.png)

## 전체 기동과 실제 Vue 관측

새 컴퓨터에서 시작한다면 [다른 컴퓨터 실행·개발 안내](<가상 제조공장 실시간 통합 관제 시스템 - 다른 컴퓨터 실행·개발 안내.md>)를 먼저 따릅니다. Docker 준비·환경 파일 생성·Python 3.12 설정부터 설명하며, 기존 데이터가 있는 pull 환경의 절차도 구분합니다.

```sh
scripts/dev-stack.sh env       # 처음 한 번만. 기존 .env를 덮어쓰지 않음
scripts/dev-stack.sh up
scripts/dev-stack.sh status
# 사용 후 DB 파일을 보존하며 종료
scripts/dev-stack.sh down
```

기동된 [Vue 관측 앱](http://127.0.0.1:5173)에서 실제 실행을 선택합니다. 새 차체를 시연하려면 다음 명령을 실행하고 출력된 runId를 선택하세요. 일반 기동은 자동 생산하지 않습니다.

```sh
INGESTION_TCP_HOST=127.0.0.1 INGESTION_TCP_PORT=9090 scripts/simulator.sh run --connected-demo --traffic
```

[실제 LIVE 화면](services/factory-console/preview-s06-live.jpg) · [소스 중단](services/factory-console/preview-s06-source-stopped.jpg) · [GOOD/PASS 태그 창](services/factory-console/preview-s06-tag.jpg)을 남겼습니다. 성공한 검증 run은 자기 데이터만 정리했으므로 화면에서 새 실행을 선택하세요. 기존 factory-gui는 독립 디자인/시나리오 샘플입니다.

Docker가 없는 이번 macOS에서는 선택적인 로컬 Lima Engine을 준비했습니다. scripts/local-docker.sh start/stop으로 관리하며 VM 저장 경로는 /tmp/factory-lima-s01입니다. Compose 재기동의 DB 보존은 확인했지만 OS 임시 폴더 정리까지 보장하는 장기 저장소는 아닙니다. 실행 도구·저장 경로·최소 검증 명령은 [전체 실행 안내](infrastructure/README.md)를 따릅니다.

## S02-01 Python 모델 확인

```sh
scripts/simulator.sh run --inspect-model --initial-bodies 3
```

서버/TCP 설정 없이 새 run과 차체·태그 3쌍을 BODY-IN에 등록해 로컬 설명을 출력합니다. 작업·예약·운송·상태 보고는 진행하지 않습니다. [작업 10 설명](<docs/work-notes/작업 10. 공장 설정과 차체·태그 등록.md>)과 [Python 안내](services/factory-simulator/README.md)를 따릅니다.

## S02-02 셀 작업·검사 확인

```sh
scripts/simulator.sh run --demo-work
```

서버 없이 차체 한 대의 ASM-01 → ASM-02 → QC-01 작업 기록과 PASS 결과를 출력합니다. 작업 시간은 4/6/3초이며 결과 차체는 QC 셀에 남습니다. 이 명령의 공정 간 이동은 **시험 배치**이며 배차/예약 규칙은 별도 --demo-dispatch로 확인합니다. 모델의 AGV 운송은 아래 --demo-transport로 확인합니다. 이 오프라인 명령은 GUI 데이터 공급부가 아닙니다. 실제 연결은 S06의 --connected-demo를 사용합니다. [작업 11 설명](<docs/work-notes/작업 11. 셀 작업과 최종 검사.md>)을 참고합니다.

## S02-03 슬롯 예약·배차 확인

```sh
scripts/simulator.sh run --demo-dispatch
```

서버 없이 만석인 목적지로의 배출 승인 거절, 빈 슬롯 확보 후 차체를 셀에 보유한 배차, 마지막 슬롯의 두 요청 중 하나만 승인을 확인합니다. 기본 C=3/W=2/R=1/A=0이며 R에는 픽업 전 예약도 포함합니다. 승인된 AGV는 TO_PICKUP이고 이 배차 확인 명령에서는 픽업/운송을 진행하지 않습니다. 모델 운송은 --demo-transport로 확인합니다. [작업 12 설명](<docs/work-notes/작업 12. 슬롯 예약과 AGV 배차.md>)에 원리와 최소 검증을 기록했습니다.

## S02-04 운송·인계·슬롯 반환 확인

```sh
scripts/simulator.sh run --demo-transport
```

일반 등록 차체가 세 공정과 QC를 거쳐 GOOD에 도착하고, 빈 AGV가 귀환하는 Python 모델 흐름을 확인합니다. 별도 초기 배치에서는 C=3/W=2/R=1의 기존 예약 운송이 만석에도 정상 도착하고, 셀 진입 때 한 슬롯을 반환한 뒤 새 배차가 그 자리를 확보하는 결과를 보여 줍니다. 실행은 오프라인 tick 계산입니다. 실제 장비 연계는 범위 밖이고 이 오프라인 명령과 별도로 S06에서 TCP/GUI 최소 시나리오를 연결했습니다. [작업 13 설명](<docs/work-notes/작업 13. AGV 운송과 버퍼 슬롯 반환.md>)을 참고합니다.

## S02-05 취소·장애·부품 AMR·전체 보고 확인

```sh
scripts/simulator.sh run --demo-scenarios
```

출발 전 취소와 명시적 재시도, 고장 중 시간 보존과 복구, 예약 운송 지연, 부품 AMR 인계, 고정 FAIL 검사 후 HOLD 도착을 재현합니다. v1 사건과 전체 스냅샷을 출력하며 FINISHED로 종료합니다. 반복 취소/도착의 추가 사건 수는 0입니다. Python 테스트는 새 4개 포함 17개가 통과했고 C=2/3/4 각각 100대의 모델 정합성을 확인했습니다. S02-05 당시 사건은 로컬 기록이었고 S03에서 TCP 수집·DB 저장을 연결했습니다. S02-05 당시 관제 업무/GUI는 후속이었으며 현재 관제 업무·REST는 S04에서 완료했습니다. [작업 14 설명](<docs/work-notes/작업 14. 취소와 장애 복구 및 공장 모델 검증.md>)을 참고합니다.

## S03 수집 저장과 명시적 송신

기동한 수집기의 TCP 주소는 127.0.0.1:9090입니다. 원본 NDJSON 파일은 다음 명령으로 한 사건씩 저장 확인합니다.

```sh
INGESTION_TCP_HOST=127.0.0.1 INGESTION_TCP_PORT=9090 scripts/simulator.sh run --send-events /absolute/path/events.ndjson
# 필요한 저장/통신 경계 확인: 별도의 PostgreSQL 17.11 검증 클러스터
python3 scripts/verify-databases.py --suite ingestion
# 이미 실행 중인 Compose에서 새 run 1대 송신과 DB 원본 확인, 자기 run만 정리
python3 scripts/verify-ingestion-source.py
```

성공 ACK는 수집 DB가 원본/전달 책임을 맡았다는 뜻입니다. 아직 관제 업무 반영이나 GUI LIVE를 뜻하지 않습니다. Python 미확인 목록은 메모리이며 프로세스 종료 후 상태 복원은 P0 범위 밖입니다. [수집 실행 안내](services/ingestion-service/README.md) · [Python 실행 안내](services/factory-simulator/README.md).

## S04 관제 업무와 조회

```sh
python3 scripts/verify-databases.py --suite operations
python3 scripts/verify-operations.py
```

첫 명령은 별도 임시 PostgreSQL에서 S04의 핵심 경계 7개만 확인합니다. 두 번째는 기동한 Compose에 새 UUID run의 모델 사건 60건을 명시적으로 HTTP 반영하고, DB 원본/태그 HOLD/품질/알람을 확인한 뒤 자기 run만 정리합니다. 검증 UUID의 기존 행이 있으면 쓰기와 정리를 거절합니다. 자동 outbox 전달이나 전체 GUI 연결 증거로 설명하지 않습니다. [관제 안내](services/operations-service/README.md)와 작업19~22를 참고합니다.

## S05 자동 전달·복구·진단

- [S05-01 / 작업23](<docs/work-notes/작업 23. S05-01 영속 outbox와 자동 HTTP 전달.md>): 발송 장부·HTTP worker·시도 제한과 완료/커서 동시 저장.
- [S05-02 / 작업24](<docs/work-notes/작업 24. S05-02 전달 결과와 순서·격리.md>): 응답 유실·중복 성공·순번/참조 대기·영구 거절.
- [S05-03 / 작업25](<docs/work-notes/작업 25. S05-03 재시작 복구와 전달 진단·재개.md>): DB 재개·현재 연결/대기 진단·이유를 남기는 명시적 재개.
- [수집 실행/진단 안내](services/ingestion-service/README.md) · [검증 기록](<docs/validation/최소 검증 시나리오와 도구.md>).

```sh
# 수집 코드만 반영, 기존 DB/볼륨 보존
scripts/dev-stack.sh compose up -d --build --wait --no-deps ingestion-service
# 필요한 경계만, 새 PostgreSQL 두 DB와 실제 관제 HTTP: Java8개
python3 scripts/verify-databases.py --suite delivery
# 기존 Compose에서 새 run의 정상60건 자동 전달/REST 확인
python3 scripts/verify-delivery.py
# 별도 개발 환경에서 서비스 중단/재시작까지 한 번에 확인
python3 scripts/verify-delivery.py --with-restarts
```

이번에는 Java8개와 마지막 Compose 시나리오 하나를 수행했습니다. 같은 변경에서 위 명령을 모두 반복할 필요는 없습니다. TCP ACK는 계속 수집 저장 확인이며, 이후 관제 반영은 별도 결과입니다. 실제 관제 중단 중에도 뒤 보고서가 저장됐고 수집 재시작 후 pending/커서/횟수를 유지했습니다. 복원 후 원본60건 바이트/해시 일치·pending0/커서61·REST LIVE→FINISHED/ARCHIVED·HOLD/FAIL을 확인했습니다. 성공한 새 검증 실행만 정리했으며 기존 데이터는 보존했습니다. `verify-ingestion-source.py`도 현재 자동 전달 검증으로 연결됩니다. S05 당시 GUI/SSE 연결은 후속이었으며 S06에서 최소 실제 연결을 완료했습니다.


## S07 실제 P0 관제 기능

```sh
# 기본 C=3의 정상 등록5대/부품 AMR/만석/설비 복구/품질 시나리오, 새 run을 DB에 남김
INGESTION_TCP_HOST=127.0.0.1 INGESTION_TCP_PORT=9090 scripts/simulator.sh run --connected-p0-demo
# 이미 기동한 Compose에서 이번 변경의 전체 경로 확인, 성공한 자기 UUID만 정리
python3 scripts/verify-p0-console.py
```

[실제 Vue 화면 실행/캡처](services/factory-console/README.md)에서 지도·검색·상세·품질/알람·이력 사용법을 볼 수 있습니다. 기본 helper는 실제 DB/API/SSE 검증이며 GUI를 자동으로 통과 처리하지 않습니다. 모든 서비스를 재배포한 뒤 검증을 시작합니다. 일반 Python 기동은 계속 자동 생산을 하지 않습니다. **테스트는 최소한으로, 꼭 필요한 것만 수행합니다.**

## S08 장애·복구와 100대 통합 검증

S08-01~04에서 별도 PostgreSQL과 두 서버로 예약 취소/반환·목적 셀 정지 중 도착·확인/복구, TCP ACK 유실/재전송·12초 보고 단절, 양 서비스와 개별 DB·PostgreSQL 재시작을 확인했다. 최종 5대 실행 원본216건과 100대 실행 원본3,533건은 두 DB에서 순번·바이트·해시가 일치했다. 100대의 2,764 tick에서 단일 위치/용량을 확인하고 중간 전체 스냅샷28개와 최종 상태를 관제 API와 비교했다. 작업300/검사100/운송400·PASS80/FAIL20, 검사/운송 원본 각각10회 재전송의 실적 증가0·run 격리가 통과했다. 실제 Chrome의 SSE 단절/복구·태그 선택/마지막 값 보존은 별도 실행 증거를 명시해 재사용했다. 기존 Java 관련2개만 선택 실행했고 전체 테스트·새 의존성·DDL·운영 코드 변경은 없다. 기존 스택과 흰색/네이비/파란색 UI·개발 DB/볼륨을 유지했다. 논리 공정의 정확성 검증이며 이 문단은 S08 기능 정확성 기록이다. 이후 S09에서 실제 성능을 측정했다.

[S08-01 설명](<docs/work-notes/작업 33. S08-01 만석·예약 반환과 셀 정지·정상화.md>) · [S08-02 설명](<docs/work-notes/작업 34. S08-02 TCP와 브라우저 SSE 단절·복구.md>) · [S08-03 설명](<docs/work-notes/작업 35. S08-03 서비스·DB 재시작과 지연·중복 사건.md>) · [S08-04 설명](<docs/work-notes/작업 36. S08-04 100대 정상 순환과 차체·실행 격리.md>) · [S08 통합 결과/재실행](<docs/development/S08 장애·복구 통합 검증.md>)

```sh
# 기존 Compose와 데이터에 영향을 주지 않는 별도 PG/Java 검증
.build-cache/simulator-venv/bin/python scripts/verify-recovery.py
# 실제 브라우저 단계도 포함할 때, 출력한 URL/phase에서 확인
.build-cache/simulator-venv/bin/python scripts/verify-recovery.py --browser
```

브라우저 제외 기본 실행의 browserVerified=false를 GUI 통과로 기록하지 않는다. 최종 성공은 `.build-cache/recovery-verification/05f6bac4de3e4011be194b0719399d10/result.json`이며 실제 Chrome 증거는 별도879a42e6… 실행이다. 모든 검증 DB/원본은 보존하고 자기 서버 프로세스만 종료했다.

## S09 실제 측정과 제출 자료

[S09-01 설명](<docs/work-notes/작업 37. S09-01 실제 입력 부하와 구간별 지연 측정.md>) · [S09-02 설명](<docs/work-notes/작업 38. S09-02 SQL과 실제 화면 비용 확인.md>) · [S09-03 설명](<docs/work-notes/작업 39. S09-03 초기 실행과 기존 데이터 재실행 안내.md>) · [S09-04 설명](<docs/work-notes/작업 40. S09-04 P0 완료표와 시연 산출물 정리.md>)

[S09 측정·완료 기록](<docs/development/S09 측정·완료 기록.md>) · [초기 실행/재실행/복구/시연](<docs/development/초기 실행·재실행·복구·시연.md>) · [ADR-002](<docs/decisions/ADR-002-측정 근거와 P0 완료 범위.md>) · [12회 CSV](docs/development/s09-results/pipeline.csv) · [실제 캡처/단계 재생](docs/development/s09-demo/index.html) · [21초 MP4](docs/development/s09-demo/s09-stage-playback.mp4).

정상 입력25.63~25.72건/s에서 작은 전경 화면 반영 p95 약98ms를 관측했습니다. 스트레스 목표 입력량은 만들지 못했고 관제 전달 대기/SSE 지연이 커졌습니다. 모든 성능 목표를 통과했다고 표시하지 않습니다. 같은 새 run의 W2/R1/A0→W3/R0/A0→W2/R0/A1·고장/복구·검사5/P4/F1·태그 HOLD/FAIL을 실제 화면에서 확인했습니다. 스택/흰색·네이비 UI/개발 데이터 유지, 테스트는 필요한 기존 Java2·Node2와 이번 측정·재시작·시연으로 제한했습니다.
