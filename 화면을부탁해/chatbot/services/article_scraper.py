"""뉴스 URL에서 분석에 필요한 제목·날짜·본문을 안전하게 수집한다."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup


MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MIN_ARTICLE_LENGTH = 80
ALLOWED_PORTS = {80, 443}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
USER_AGENT = (
    "Mozilla/5.0 (compatible; FactLens/0.1; "
    "+https://localhost/news-factcheck)"
)
KOREA_TIMEZONE = timezone(timedelta(hours=9))


class ArticleScrapingError(RuntimeError):
    """기사 URL 수집의 공통 오류."""


class InvalidArticleURLError(ArticleScrapingError):
    """허용할 수 없는 기사 URL."""


class ArticleFetchError(ArticleScrapingError):
    """기사 페이지를 내려받지 못한 경우."""


class ArticleExtractionError(ArticleScrapingError):
    """페이지에서 기사 본문을 찾지 못한 경우."""


@dataclass(frozen=True)
class ScrapedArticle:
    url: str
    title: str
    date: str
    body: str


Requester = Callable[..., Any]


def validate_public_article_url(url: str) -> str:
    """HTTP(S) 공개 웹 주소인지 확인해 SSRF 대상을 차단한다."""
    normalized = url.strip()
    try:
        parsed = urlsplit(normalized)
    except ValueError as error:
        raise InvalidArticleURLError("올바른 기사 URL을 입력해 주세요.") from error

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidArticleURLError("http 또는 https 기사 URL만 사용할 수 있습니다.")
    if parsed.username or parsed.password:
        raise InvalidArticleURLError("인증 정보가 포함된 URL은 사용할 수 없습니다.")

    try:
        port = parsed.port
    except ValueError as error:
        raise InvalidArticleURLError("URL 포트가 올바르지 않습니다.") from error
    if port is not None and port not in ALLOWED_PORTS:
        raise InvalidArticleURLError("기사 URL은 80 또는 443 포트만 사용할 수 있습니다.")

    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(parsed.hostname, port or 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as error:
        raise InvalidArticleURLError("기사 사이트의 주소를 확인할 수 없습니다.") from error

    if not addresses:
        raise InvalidArticleURLError("기사 사이트의 주소를 확인할 수 없습니다.")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as error:
            raise InvalidArticleURLError("기사 사이트 주소가 올바르지 않습니다.") from error
        if not ip.is_global:
            raise InvalidArticleURLError("내부망 또는 로컬 주소에는 접근할 수 없습니다.")
    return normalized


def _iter_json_objects(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _iter_json_objects(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_json_objects(nested)


def _meta_content(soup: BeautifulSoup, *keys: str) -> str:
    for key in keys:
        node = (
            soup.find("meta", attrs={"property": key})
            or soup.find("meta", attrs={"name": key})
            or soup.find("meta", attrs={"itemprop": key})
        )
        if node and node.get("content"):
            return str(node["content"]).strip()
    return ""


def _normalize_date(value: str) -> str:
    normalized = value.strip()
    iso_value = normalized
    if iso_value.lower().endswith("z"):
        iso_value = f"{iso_value[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(KOREA_TIMEZONE)
        return parsed.date().isoformat()

    match = re.search(
        r"(?<!\d)(\d{4})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})",
        normalized,
    )
    if not match:
        return normalized
    year, month, day = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def _clean_text(value: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in value.replace("\xa0", " ").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines).strip()


def _structured_article_data(soup: BeautifulSoup) -> tuple[str, str, str]:
    best_body = ""
    title = ""
    date = ""
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for item in _iter_json_objects(payload):
            body = item.get("articleBody")
            if isinstance(body, str) and len(body) > len(best_body):
                best_body = body
            if not title and isinstance(item.get("headline"), str):
                title = item["headline"]
            if not date and isinstance(item.get("datePublished"), str):
                date = item["datePublished"]
    return _clean_text(best_body), title.strip(), _normalize_date(date)


def _fusion_article_data(soup: BeautifulSoup) -> tuple[str, str, str]:
    """Arc Publishing의 Fusion 메타데이터에서 기사 본문을 추출한다."""
    assignment_pattern = re.compile(r"(?:window\.)?Fusion\.globalContent\s*=\s*")
    decoder = json.JSONDecoder()
    best_body = ""
    title = ""
    date = ""

    for script in soup.find_all("script"):
        raw = script.string or script.get_text()
        if "Fusion.globalContent" not in raw:
            continue

        for match in assignment_pattern.finditer(raw):
            candidate = raw[match.end() :].lstrip()
            try:
                payload, _ = decoder.raw_decode(candidate)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue

            paragraphs: list[str] = []
            elements = payload.get("content_elements")
            if isinstance(elements, list):
                for element in elements:
                    if not isinstance(element, dict):
                        continue
                    if str(element.get("type", "")).lower() not in {"text", "header"}:
                        continue
                    content = element.get("content")
                    if not isinstance(content, str):
                        continue
                    fragment = BeautifulSoup(content, "html.parser")
                    for break_node in fragment.select("br"):
                        break_node.replace_with("\n")
                    text = _clean_text(fragment.get_text("", strip=False))
                    if text:
                        paragraphs.append(text)

            body = _clean_text("\n".join(paragraphs))
            if len(body) > len(best_body):
                best_body = body
                headlines = payload.get("headlines")
                if isinstance(headlines, dict):
                    basic = headlines.get("basic")
                    if isinstance(basic, str):
                        title = basic.strip()
                for key in ("display_date", "first_publish_date", "created_date"):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        date = _normalize_date(value)
                        break

    return best_body, title, date


def extract_article(html: str, url: str) -> ScrapedArticle:
    """HTML 메타데이터와 본문 후보를 비교해 가장 긴 기사 본문을 선택한다."""
    soup = BeautifulSoup(html, "html.parser")
    structured_body, structured_title, structured_date = _structured_article_data(soup)
    fusion_body, fusion_title, fusion_date = _fusion_article_data(soup)

    title = (
        _meta_content(soup, "og:title", "twitter:title")
        or structured_title
        or fusion_title
    )
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    date = fusion_date or _meta_content(
        soup,
        "article:published_time",
        "datePublished",
        "date",
        "pubdate",
    ) or structured_date
    if not date:
        time_node = soup.find("time", attrs={"datetime": True})
        if time_node:
            date = str(time_node["datetime"])

    for node in soup.select("script, style, noscript, iframe, svg, nav, aside, form, button"):
        node.decompose()

    candidates = [structured_body, fusion_body]
    selectors = (
        "article",
        "[itemprop='articleBody']",
        "#dic_area",
        "#newsct_article",
        "#articleBody",
        "#article-body",
        ".article-body",
        ".article_view",
        ".article-text",
        ".article_txt",
        ".view_cont",
    )
    for node in soup.select(", ".join(selectors)):
        paragraphs = [
            part.get_text(" ", strip=True)
            for part in node.select("p")
            if part.get_text(" ", strip=True)
        ]
        text = "\n".join(paragraphs) if paragraphs else node.get_text("\n", strip=True)
        candidates.append(_clean_text(text))

    body = max(candidates, key=len, default="")
    if len(body) < MIN_ARTICLE_LENGTH:
        raise ArticleExtractionError(
            "페이지에서 기사 본문을 찾지 못했습니다. 본문 직접 입력을 이용해 주세요."
        )
    return ScrapedArticle(
        url=url,
        title=_clean_text(title),
        date=_normalize_date(date),
        body=body,
    )


def _response_bytes(response: Any) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_RESPONSE_BYTES:
                raise ArticleFetchError("기사 페이지 용량이 너무 큽니다.")
        except ValueError:
            pass

    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise ArticleFetchError("기사 페이지 용량이 너무 큽니다.")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_article(url: str, *, requester: Requester = requests.get) -> ScrapedArticle:
    """리다이렉트를 검증하며 기사 페이지를 받고 본문을 추출한다."""
    current_url = validate_public_article_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}

    for redirect_count in range(MAX_REDIRECTS + 1):
        try:
            response = requester(
                current_url,
                headers=headers,
                timeout=(5, 15),
                stream=True,
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise ArticleFetchError("기사 페이지에 접속하지 못했습니다.") from error

        try:
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise ArticleFetchError("기사 사이트의 이동 주소가 비어 있습니다.")
                if redirect_count >= MAX_REDIRECTS:
                    raise ArticleFetchError("기사 사이트의 이동 횟수가 너무 많습니다.")
                current_url = validate_public_article_url(urljoin(current_url, location))
                continue
            if response.status_code < 200 or response.status_code >= 300:
                raise ArticleFetchError(
                    f"기사 사이트가 HTTP {response.status_code} 응답을 반환했습니다."
                )
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                raise ArticleFetchError("HTML 기사 페이지만 분석할 수 있습니다.")
            payload = _response_bytes(response)
            encoding = response.encoding
            if not encoding or encoding.lower() == "iso-8859-1":
                encoding = response.apparent_encoding or "utf-8"
            html = payload.decode(encoding, errors="replace")
            return extract_article(html, current_url)
        finally:
            response.close()

    raise ArticleFetchError("기사 페이지를 가져오지 못했습니다.")


__all__ = [
    "ArticleExtractionError",
    "ArticleFetchError",
    "ArticleScrapingError",
    "InvalidArticleURLError",
    "ScrapedArticle",
    "extract_article",
    "fetch_article",
    "validate_public_article_url",
]
