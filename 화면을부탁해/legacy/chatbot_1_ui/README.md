# Chatbot

기사 원문을 입력받아 기존 수치 주장 추출·KOSIS 검증 파이프라인을 호출하는 제품 계층입니다.

## 경계

- 루트의 기존 `*.py`: 배치 파이프라인과 도메인 로직
- `chatbot/`: 원문 입력, 파이프라인 조합, 사용자용 응답, API/UI

기존 파이프라인 파일은 바로 이동하지 않습니다. 현재 import 구조와 회귀 테스트를 유지하면서 `chatbot/services/` 어댑터를 통해 재사용합니다.

## 예정 구조

```text
chatbot/
├─ __init__.py
├─ README.md
├─ schemas.py                 # 기사 입력·분석 결과 형식 (완료)
├─ api.py                     # FastAPI 엔드포인트 (완료)
└─ services/
   ├─ __init__.py
   ├─ article_scraper.py      # URL 기사 제목·날짜·본문 수집
   ├─ article_pipeline.py     # 기존 파이프라인 조합
   ├─ analysis_service.py     # 전체 분석 조합
   ├─ kosis_pipeline.py       # KOSIS 검색·검증 어댑터
   └─ response_builder.py     # 사용자용 응답 생성 (완료)
```

## 첫 구현 순서

1. ~~원문 문자열을 `preprocess_news.preprocess_articles()`에 연결한다.~~
2. HCX 통계 주장 판별을 연결한다. **(완료)**
3. measurement 추출을 연결한다. **(완료)**
4. KOSIS 결과와 반려 결과를 `claim_measurement_id`로 병합한다. **(완료)**
5. 결과를 `일치 / 불일치 / 판정보류 / 판단불가`로 안전하게 표시한다.

### 원문 전처리 예시

```python
from chatbot.services.article_pipeline import preprocess_article

result = preprocess_article(
    "소비자물가는 전년보다 2.3% 상승했다.",
    title="물가 기사",
    date="2026-08-04",
)

for sentence in result["sentences"]:
    print(sentence["claim_id"], sentence["claim_text"])
```

HCX 주장 판별까지 한 번에 실행하려면:

```python
from chatbot.services.article_pipeline import detect_article_claims

result = detect_article_claims(
    "통계청이 발표했다. 소비자물가는 2.3% 상승했다.",
    title="물가 기사",
    date="2026-08-04",
)

print(result["claims"])
```

measurement 추출까지 실행하려면:

```python
from chatbot.services.article_pipeline import analyze_article_measurements

result = analyze_article_measurements(
    "통계청이 발표했다. 소비자물가는 2.3% 상승했다.",
    title="물가 기사",
    date="2026-08-04",
)

print(result["measurements"])
```

KOSIS를 연결하려면:

```python
from chatbot.services.kosis_pipeline import run_kosis_pipeline

kosis_result = run_kosis_pipeline(result, mode="metadata")
print(kosis_result["results"])
```

- `mode="table"`: 로컬 lexical 통계표 검색까지
- `mode="metadata"`: KOSIS 메타 API로 ITEM·OBJ 후보 판정까지
- `mode="verify"`: KOSIS 실제값 조회와 verdict까지

## API 계약

`ArticleAnalyzeRequest`는 기사 원문·제목·날짜·URL과 KOSIS 실행 모드를
받는다. `ArticleAnalyzeResponse`는 문장별 주장 판별, measurement별 KOSIS
판정, 단계별 집계를 안정적인 JSON 형식으로 반환한다.

화면에서는 다음 두 입력 방식 중 하나를 선택할 수 있다.

1. **본문 직접 입력**: 기사 원문과 기사 날짜를 입력한다. 제목은 선택이다.
2. **기사 URL 입력**: 공개 기사 URL을 입력하면 서버가 제목·작성일·본문을
   자동 수집하고 같은 분석 파이프라인으로 전달한다.

URL 방식은 `POST /api/articles/analyze-url`을 사용한다. HTTP(S) 공개 주소만
허용하며 내부망 주소, 80·443 이외 포트, 5MB 초과 페이지는 차단한다. 로그인,
유료 구독 또는 브라우저 자바스크립트 실행이 필요한 기사는 직접 입력을 사용한다.

## FastAPI 실행

```powershell
py -3.13 -m pip install -r requirements.txt
py -3.13 -m uvicorn chatbot.api:app --reload
```

- API 문서: `http://127.0.0.1:8000/docs`
- 챗봇 화면: `http://127.0.0.1:8000/`
- 상태 확인: `GET /health`
- 기사 분석: `POST /api/articles/analyze`
- URL 기사 수집·분석: `POST /api/articles/analyze-url`
