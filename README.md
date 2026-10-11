# Telegram Trend Intelligence

공개 Telegram 채널의 종목 언급·반복 이슈·원문 근거와 실제 로컬 AI 요약을 탐색하는 한국어 FastAPI 대시보드입니다. Python 3.11 이상을 사용합니다.

## 실행

```powershell
git clone https://github.com/haeseokoh/Telegram_trend.git
cd Telegram_trend
python -m pip install -r requirements.txt
python main.py --port 8010
```

브라우저에서 http://127.0.0.1:8010 을 엽니다. 로컬 컴퓨터에만 바인딩합니다. 첫 실행에 `sample_data/`를 `data/`로 복사하고 `channels.example.json`을 사용자 설정 `channels.json`으로 초기화합니다. 기존 설정·수집 데이터가 있으면 유지합니다. 외부 CDN·웹 데이터베이스 없이 동작합니다.

Windows에서는 다음 명령으로 바탕화면 바로가기를 만들 수 있습니다. OneDrive 등 리디렉션된 Desktop 경로도 인식하고 기존 파일을 덮어쓰지 않습니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\create_desktop_shortcut.ps1
```

바로가기의 `launch_dashboard.ps1`은 꺼진 서버를 숨김 실행하고 준비 후 기본 브라우저를 엽니다. 실행 중인 이 앱의 서버는 재사용합니다. 다른 앱이 같은 포트를 사용하면 안내합니다. 런처는 프로젝트의 가상환경, 저장된 로컬 Python 경로 또는 설치된 Python을 사용합니다. 의존성 설치는 위 명령으로 한 번 진행해야 합니다.

## 채널 추가·제외와 수집

상단 **채널 관리**에서 공개 링크(`https://t.me/channel_name`, `https://t.me/s/channel_name`) 또는 `@channel_name`을 입력하고 **채널 등록 · 공개 확인**을 클릭합니다. 공개 메시지 미리보기를 확인한 채널만 등록하며 임의·로컬 URL, 초대/게시물 링크, 비공개 채널·그룹·개인 계정은 지원하지 않습니다. Telegram 요청은 고정된 공개 미리보기 주소를 사용하고 리디렉션을 따라가지 않습니다.

등록 후 수집 시작일·종료일을 고르고 채널의 **선택 기간 수집**을 클릭합니다. KST 기준 종료일까지 포함하며 오늘까지 최대 367일을 지정할 수 있습니다. 한 번에 한 작업이 백그라운드에서 실행되고 페이지·건수·수집 경계·분석·실패 상태를 표시합니다. 창을 닫아도 서버가 실행 중이면 계속 진행합니다. 완료하면 통계·검색·CSV·AI 입력에 반영합니다.

**비활성화**는 분석 대상에서 제외하고 기존 자료를 보존합니다. **재활성화**하면 다시 조회할 수 있습니다. 같은 기간을 재수집해도 다른 기간의 글과 기존 관측 자료는 유지합니다. 동일 URL의 본문은 최신 응답으로 갱신하고 이전 데이터와 HTML은 `data/collection_history/`에 보관합니다. 재시작으로 중단된 작업은 중단으로 표시하며 데이터 교체 도중 중단됐으면 이전 출력을 복원합니다. 자동 재시도·예약 수집은 없습니다.

미수집·수집 경계 미확인 날짜는 안내하며, 확보한 언급이 없을 때 타임라인에 0 대신 미수집을 표시합니다. 긴 기간·게시량이 많은 채널은 최대 페이지 제한으로 일부만 수집될 수 있습니다. 이미지/PDF/영상 내부와 기사 링크 목적지 본문은 분석하지 않습니다. 종목 탐지는 확장 별칭 사전 기준이며 사전 밖 이름·별칭은 누락될 수 있습니다.

## AI 요약

Ollama와 생성 모델이 로컬에서 실행되어 있으면 **선택 범위 AI 브리프**, 메시지별 **AI 3줄 요약**, 종목 상세의 **AI 종합 브리프**를 사용할 수 있습니다. 기본 주소는 `http://localhost:11434`, 기본 모델은 `qwen3:8b`이며 설치된 다른 생성 모델도 선택할 수 있습니다. `OLLAMA_BASE_URL`, `DEFAULT_LLM_MODEL` 환경변수로 설정합니다. 별도 API 키·유료 서비스 가입은 필요하지 않습니다.

한 줄 결론·3줄 요약·논거·전망·리스크와 원문, 모델·시각·표본 수·생략 여부를 표시합니다. 종합 요약은 채널별 첫 줄 종목 언급을 우선하고 유사 본문을 제외한 최대 12건을 사용합니다. 전체 게시물의 전수 AI 분석은 아닙니다. 긴 본문은 일부 생략하며 AI 해석에는 추론·오류가 포함될 수 있습니다.

AI 결과는 `.runtime/ai_cache.json`에 저장하고 본문·모델·요약 종류가 바뀌면 새로 생성합니다. **AI 다시 생성**은 캐시를 건너뜁니다. 실패·타임아웃·불완전 응답을 오류로 표시하며 규칙 문장을 AI 결과로 대체하지 않습니다. 통계 기반 관심 브리프와 저장된 수작업 이슈는 실제 AI 결과와 구분합니다.

## 포함된 샘플

2026-10-05~10-11의 8채널 샘플 557건입니다. 마지막 날은 10/11 12:00 KST까지의 부분 일자입니다.

|채널 ID|글|
|---|---:|
|infomarketopen|417|
|hslpartners|22|
|eqmirae|4|
|sejongdata2013|14|
|kiwoom_semibat|40|
|hanasmallcap|1|
|Ibks_innovation_research|10|
|eng999view|49|

`sample_data/`에는 앱 실행·검색·AI 입력·회귀 검증에 필요한 공개 메시지와 집계만 포함합니다. 원시 HTML, 개인 설정, AI 캐시, 작업 이력, 의존성·임시 폴더는 저장소에서 제외합니다. 실제 로컬 사용자 데이터는 Git으로 덮어쓰지 않습니다. 샘플 분석은 [docs/SAMPLE_REPORT.md](docs/SAMPLE_REPORT.md), 실행 검증은 [WEB_VALIDATION.md](WEB_VALIDATION.md)를 참고하세요.

## CLI 재수집·검증

```powershell
python collect.py
python report.py
python verify.py
```

CLI 수집도 활성 채널만 대상으로 병합·분석하고 기존 자료를 보존합니다. 기본 기간은 저장된 기본 기간이며 `TELEGRAM_START`, `TELEGRAM_END_EXCLUSIVE`(종료일 다음 날)로 지정합니다. 완료 후 웹의 **저장 데이터 새로고침**을 누릅니다. 수작업 이슈 편집 원본은 `issues_catalog.json`입니다.

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python verify.py
node --check app/static/js/dashboard.js
node --check app/static/js/ai.js
node --check app/static/js/channels.js
```

35개 테스트가 고정 샘플과 격리된 설정·작업 파일을 사용하므로 사용자 채널 설정을 변경하지 않습니다. 배포 샘플의 본문 해시·집계·날짜·근거를 검사하고, 로컬 원시 HTML을 보유한 데이터에서는 HTML 포함 여부도 검사합니다.

## 구성

- `app/main.py`, `app/service.py`: API·필터·집계·검색·CSV
- `app/channel_manager.py`: 영구 설정·공개 확인·백그라운드 수집·복원
- `app/ai.py`: 로컬 Ollama·구조화 응답·캐시
- `app/static/`: 한국어 화면·차트·테마·모바일·채널 관리
- `collect.py`, `analyze.py`, `report.py`, `verify.py`: 수집·사전 분석·보고서·검증
- `channels.example.json`, `domestic_aliases.json`, `foreign_aliases.json`: 기본 채널과 확장 별칭
