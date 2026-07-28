import csv
import subprocess
import sys
from pathlib import Path

from preprocess_news import (
    clean_article_body,
    preprocess_articles,
    resolve_columns,
    split_sentences_regex,
)


def test_clean_article_body_removes_html_scripts_and_footer_noise():
    raw = """
    <article>
      <p>소비자물가는 전년보다 2.3% 상승했다.</p>
      <script>ignore_me()</script>
      <p>통계청이 2일 발표했다.</p>
    </article>
    무단 전재 및 재배포 금지
    """

    cleaned = clean_article_body(raw)

    assert "소비자물가는 전년보다 2.3% 상승했다." in cleaned
    assert "통계청이 2일 발표했다." in cleaned
    assert "ignore_me" not in cleaned
    assert "무단 전재" not in cleaned


def test_clean_article_body_removes_crawler_page_prefix_and_byline():
    title = "최저임금 1만30원으로 인상"
    raw = (
        "신문구독 | 정치 사회 국제 "
        f"{title} 새해부터 달라지는 제도 김희래 기자 "
        "입력 2025.01.01. 01:28 업데이트 2025.01.02. 16:12 "
        "1 최저임금이 시간당 1만30원으로 인상된다."
    )

    cleaned = clean_article_body(raw, title=title)

    assert cleaned == "최저임금이 시간당 1만30원으로 인상된다."


def test_clean_article_body_stops_before_comments_and_site_footer():
    title = "전기차 정보 관리 논란"
    raw = (
        f"{title} 조재희 기자 입력 2025.01.01. 00:35 "
        "회사는 외부 접근을 막았다고 밝혔다. "
        "#전기차 조재희 기자 구독수 216 100자평 3 "
        "댓글 내용이다. AI 추천 다른 기사"
    )

    cleaned = clean_article_body(raw, title=title)

    assert cleaned == "회사는 외부 접근을 막았다고 밝혔다."


def test_preprocess_articles_assigns_ids_and_sentence_context():
    articles = [
        {
            "기사제목": "물가 기사",
            "작성일": "2026-07-20",
            "URL": "https://example.com/news/1",
            "본문": "소비자물가는 2.3% 상승했다. 전월보다는 0.2% 올랐다.",
        },
        {
            "기사제목": "고용 기사",
            "작성일": "2026-07-21",
            "URL": "https://example.com/news/2",
            "본문": "취업자는 10만명 증가했다.",
        },
    ]
    columns = resolve_columns(articles[0].keys(), {})

    rows, empty_articles = preprocess_articles(
        articles, columns, split_sentences_regex
    )

    assert empty_articles == 0
    assert [row["claim_id"] for row in rows] == [
        "A0001-C001",
        "A0001-C002",
        "A0002-C001",
    ]
    assert [row["article_id"] for row in rows] == ["A0001", "A0001", "A0002"]
    assert rows[0]["prev_sentence"] == ""
    assert rows[0]["next_sentence"] == "전월보다는 0.2% 올랐다."
    assert rows[1]["prev_sentence"] == "소비자물가는 2.3% 상승했다."
    assert rows[1]["next_sentence"] == ""


def test_regex_splitter_handles_ellipsis_and_policy_bullets():
    text = "양육비를 선지급한다… 국가 검진도 확대한다. ▲ 급여도 인상한다."

    assert split_sentences_regex(text) == [
        "양육비를 선지급한다…",
        "국가 검진도 확대한다.",
        "▲ 급여도 인상한다.",
    ]


def test_cli_creates_hcx_input_csv(tmp_path):
    input_path = tmp_path / "articles.csv"
    output_path = tmp_path / "sentences.csv"
    with input_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["title", "date", "url", "content"])
        writer.writeheader()
        writer.writerow(
            {
                "title": "인구 기사",
                "date": "2026-07-20",
                "url": "https://example.com/news/3",
                "content": "출생아 수가 3% 증가했다. 혼인 건수도 늘었다.",
            }
        )

    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(project_root / "preprocess_news.py"),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--splitter",
            "regex",
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )

    with output_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    assert "Created:" in result.stdout
    assert len(rows) == 2
    assert rows[0]["claim_id"] == "A0001-C001"
    assert rows[0]["claim_text"] == "출생아 수가 3% 증가했다."
    assert rows[1]["claim_text"] == "혼인 건수도 늘었다."
