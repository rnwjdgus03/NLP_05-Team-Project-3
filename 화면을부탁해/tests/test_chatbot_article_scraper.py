import json
from unittest.mock import patch

import pytest

from chatbot.services.article_scraper import (
    ArticleExtractionError,
    ArticleFetchError,
    InvalidArticleURLError,
    extract_article,
    fetch_article,
    validate_public_article_url,
)


ARTICLE_BODY = (
    "통계청은 올해 소비자물가가 지난해보다 2.3% 상승했다고 발표했다. "
    "이번 수치는 전국 소비자 가격을 조사해 산출한 공식 통계다. "
    "정부는 물가 흐름을 지속해서 점검할 계획이라고 설명했다."
)


def test_extract_article_prefers_json_ld_article_data():
    html = f"""
    <html><head>
      <meta property="og:title" content="물가 상승률 기사">
      <script type="application/ld+json">
        {{"@type":"NewsArticle","datePublished":"2026-08-03T09:10:00+09:00",
          "articleBody":{ARTICLE_BODY!r}}}
      </script>
    </head><body><nav>메뉴</nav></body></html>
    """.replace("'", '"')

    article = extract_article(html, "https://news.example/article/1")

    assert article.title == "물가 상승률 기사"
    assert article.date == "2026-08-03"
    assert article.body == ARTICLE_BODY


def test_extract_article_uses_article_element_and_time_metadata():
    html = f"""
    <html><head><title>고용 기사</title></head><body>
      <time datetime="2026.07.31">2026년 7월 31일</time>
      <article><p>{ARTICLE_BODY}</p><aside>관련 기사</aside></article>
    </body></html>
    """

    article = extract_article(html, "https://news.example/article/2")

    assert article.title == "고용 기사"
    assert article.date == "2026-07-31"
    assert "관련 기사" not in article.body
    assert article.body == ARTICLE_BODY


def test_extract_article_uses_fusion_global_content():
    fusion_body = ARTICLE_BODY.replace("통계청", "<strong>통계청</strong>")
    payload = {
        "headlines": {"basic": "내수 활성화 기사"},
        "display_date": "2025-01-02T15:50:00Z",
        "content_elements": [
            {"type": "image", "caption": "기사 사진"},
            {"type": "text", "content": fusion_body},
            {"type": "header", "content": "정부 대책"},
            {"type": "text", "content": "정부는 추가 대책을 검토할 예정이다."},
        ],
    }
    html = f"""
    <html><head>
      <meta property="article:published_time" content="2025-01-02T05:17:02.250Z">
    </head><body>
      <div id="fusion-app"></div>
      <script id="fusion-metadata">
        window.Fusion = window.Fusion || {{}};
        Fusion.globalContent={json.dumps(payload, ensure_ascii=False)};
        Fusion.globalContentConfig={{}};
      </script>
    </body></html>
    """

    article = extract_article(html, "https://www.chosun.com/economy/example/")

    assert article.title == "내수 활성화 기사"
    assert article.date == "2025-01-03"
    assert article.body == (
        f"{ARTICLE_BODY}\n정부 대책\n정부는 추가 대책을 검토할 예정이다."
    )


def test_extract_article_rejects_page_without_article_body():
    with pytest.raises(ArticleExtractionError, match="본문"):
        extract_article("<html><body><p>짧은 안내</p></body></html>", "https://example.com")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/news",
        "http://localhost/news",
        "http://10.0.0.1/news",
        "https://user:password@example.com/news",
        "https://example.com:8080/news",
    ],
)
def test_validate_public_article_url_blocks_unsafe_targets(url):
    with pytest.raises(InvalidArticleURLError):
        validate_public_article_url(url)


class FakeResponse:
    def __init__(self, *, status_code=200, headers=None, body=b""):
        self.status_code = status_code
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}
        self.body = body
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"
        self.closed = False

    def iter_content(self, chunk_size):
        del chunk_size
        yield self.body

    def close(self):
        self.closed = True


def test_fetch_article_extracts_downloaded_html():
    response = FakeResponse(body=f"<article><p>{ARTICLE_BODY}</p></article>".encode())

    with patch(
        "chatbot.services.article_scraper.validate_public_article_url",
        side_effect=lambda value: value,
    ):
        article = fetch_article("https://news.example/1", requester=lambda *args, **kwargs: response)

    assert article.body == ARTICLE_BODY
    assert response.closed is True


def test_fetch_article_rejects_non_html_response():
    response = FakeResponse(headers={"content-type": "application/pdf"})

    with patch(
        "chatbot.services.article_scraper.validate_public_article_url",
        side_effect=lambda value: value,
    ):
        with pytest.raises(ArticleFetchError, match="HTML"):
            fetch_article("https://news.example/file", requester=lambda *args, **kwargs: response)
