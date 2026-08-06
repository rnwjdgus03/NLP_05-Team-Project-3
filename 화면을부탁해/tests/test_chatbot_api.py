import asyncio

import httpx

from chatbot.api import create_app
from chatbot.schemas import AnalysisSummary, ArticleAnalyzeResponse
from chatbot.services.kosis_pipeline import KosisPipelineError
from chatbot.services.article_scraper import ArticleFetchError, ScrapedArticle


def request(app, method, path, **kwargs):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def successful_service(request, request_id):
    return ArticleAnalyzeResponse(
        request_id=request_id,
        article_id=request.article_id,
        title=request.title,
        date=request.date,
        url=request.url,
        kosis_mode=request.kosis_mode,
        summary=AnalysisSummary(
            sentence_count=1,
            claim_count=0,
            measurement_count=0,
            eligible_count=0,
            rejected_count=0,
            candidate_count=0,
            mapping_count=0,
            verified_count=0,
        ),
    )


def test_health_endpoint():
    response = request(create_app(successful_service), "GET", "/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "news-factcheck-chatbot",
    }


def test_chatbot_home_and_static_assets_are_served():
    app = create_app(successful_service)

    home = request(app, "GET", "/")
    css = request(app, "GET", "/static/styles.css")
    javascript = request(app, "GET", "/static/app.js")

    assert home.status_code == 200
    assert 'id="analysisForm"' in home.text
    assert "팩트렌즈" in home.text
    assert css.status_code == 200
    assert ".measurement-card" in css.text
    assert javascript.status_code == 200
    assert "본문 직접 입력" in home.text
    assert "기사 URL 입력" in home.text
    assert 'id="articleDate" type="date" max="9999-12-31"' in home.text
    assert 'endpoint = "/api/articles/analyze"' in javascript.text
    assert 'endpoint = "/api/articles/analyze-url"' in javascript.text
    assert "기사 연도는 4자리로 입력해 주세요." in javascript.text


def test_analyze_endpoint_uses_public_request_and_response_contract():
    response = request(
        create_app(successful_service),
        "POST",
        "/api/articles/analyze",
        json={
            "body": "통계청이 발표했다.",
            "title": "통계 기사",
            "article_id": "NEWS-001",
            "splitter": "regex",
            "kosis_mode": "table",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["request_id"]
    assert payload["article_id"] == "NEWS-001"
    assert payload["kosis_mode"] == "table"
    assert payload["summary"]["sentence_count"] == 1


def test_analyze_endpoint_returns_stable_validation_error():
    response = request(
        create_app(successful_service),
        "POST",
        "/api/articles/analyze",
        json={"body": "   "},
    )

    payload = response.json()
    assert response.status_code == 422
    assert payload["request_id"]
    assert payload["error"]["code"] == "INVALID_REQUEST"
    assert payload["error"]["stage"] == "request"


def test_analyze_endpoint_maps_kosis_failure_to_502():
    def failed_service(request, request_id):
        raise KosisPipelineError("KOSIS timeout")

    response = request(
        create_app(failed_service),
        "POST",
        "/api/articles/analyze",
        json={"body": "소비자물가는 2.3% 상승했다."},
    )

    payload = response.json()
    assert response.status_code == 502
    assert payload["error"]["code"] == "KOSIS_PIPELINE_FAILED"
    assert payload["error"]["stage"] == "kosis"


def test_analyze_url_fetches_article_then_uses_existing_analysis_service():
    scraped = ScrapedArticle(
        url="https://news.example/final",
        title="자동 수집 기사",
        date="2026-08-03",
        body="소비자물가는 지난해보다 2.3% 상승했다.",
    )
    response = request(
        create_app(successful_service, article_fetcher=lambda url: scraped),
        "POST",
        "/api/articles/analyze-url",
        json={"url": "https://news.example/original", "kosis_mode": "verify"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["title"] == "자동 수집 기사"
    assert payload["date"] == "2026-08-03"
    assert payload["url"] == "https://news.example/final"
    assert payload["kosis_mode"] == "verify"


def test_analyze_url_maps_fetch_failure_to_stable_error():
    def failed_fetcher(url):
        raise ArticleFetchError("기사 페이지에 접속하지 못했습니다.")

    response = request(
        create_app(successful_service, article_fetcher=failed_fetcher),
        "POST",
        "/api/articles/analyze-url",
        json={"url": "https://news.example/article"},
    )

    payload = response.json()
    assert response.status_code == 502
    assert payload["error"]["code"] == "ARTICLE_FETCH_FAILED"
    assert payload["error"]["stage"] == "article_fetch"
