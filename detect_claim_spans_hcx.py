"""Detect broad quantitative/statistical claim spans in news chunks with HCX.

This stage deliberately does not decide whether a claim is in KOSIS scope.
The output is claim-level evidence that can be sent to early BGE retrieval and
then to measurement structuring.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv


URL = "https://clovastudio.stream.ntruss.com/v3/chat-completions/{model}"
PROMPT_VERSION = "claim-span-v1.0-broad-no-kosis-gate"

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "spans": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_sentence_id": {"type": "string"},
                    "end_sentence_id": {"type": "string"},
                    "claim_text": {"type": "string"},
                    "claim_type": {
                        "type": "string",
                        "enum": [
                            "numeric_level",
                            "numeric_change",
                            "numeric_comparison",
                            "statistical_direction",
                        ],
                    },
                    "reason": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "mid", "low"],
                    },
                },
                "required": [
                    "start_sentence_id",
                    "end_sentence_id",
                    "claim_text",
                    "claim_type",
                    "reason",
                    "confidence",
                ],
            },
        }
    },
    "required": ["spans"],
}

SYSTEM_PROMPT = """당신은 한국어 뉴스에서 수치·통계 주장의 원문 범위를 찾는 데이터 라벨러다.

이 단계에서는 KOSIS에 있는지, 국내 통계인지, 검증 가능한지는 절대 판단하지 않는다.
다음 중 하나면 넓게 claim span으로 잡는다.
- 금액, 인원, 비율, 지수, 순위, 수량 등 관측값을 말한다.
- 이전 시점이나 집단과 비교해 증가·감소·차이를 말한다.
- 숫자가 생략됐어도 특정 통계 지표의 상승·하락·증가·감소를 주장한다.

날짜, 주소, 모델명, 법 조항, 단순 목록 번호만 있는 문장은 제외한다.
근거가 여러 문장에 걸치면 필요한 최소 연속 문장 범위를 반환한다.
문장을 요약하거나 번역하지 말고 입력에 표시된 sentence_id 경계를 사용한다.
겹치는 주장은 하나의 span으로 합치고 JSON만 출력한다."""

USER_TEMPLATE = """기사 제목: {title}
기사 날짜: {date}
chunk 이전 문장: {prev_sentence}

[분석할 문장]
{chunk_text}

chunk 다음 문장: {next_sentence}

수치·통계 claim span을 모두 JSON으로 반환하라. KOSIS 가능성은 판단하지 마라."""

OUTPUT_COLUMNS = [
    "claim_id",
    "claim_span_id",
    "article_id",
    "chunk_id",
    "title",
    "date",
    "url",
    "claim_text",
    "detected_claim_text",
    "prev_sentence",
    "next_sentence",
    "evidence_sentence_ids",
    "span_start_sentence_id",
    "span_end_sentence_id",
    "claim_span_type",
    "is_claim",
    "is_claim_reason",
    "is_claim_confidence",
    "is_claim_method",
    "extraction_model",
    "prompt_version",
    "extracted_at",
]

PROGRESS_COLUMNS = ["chunk_id", "span_count", "processed_at"]


def _json_list(value: str, field: str) -> list[str]:
    try:
        result = json.loads(value)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"{field} must contain a JSON array") from error
    if not isinstance(result, list):
        raise ValueError(f"{field} must contain a JSON array")
    return [str(item).strip() for item in result]


def span_key(article_id: str, start_id: str, end_id: str) -> str:
    return f"{article_id}|{start_id}|{end_id}"


def stable_span_id(key: str) -> str:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10].upper()
    return f"SP{digest}"


def build_span_rows(
    chunk: dict[str, str],
    response: dict,
    model: str,
    extracted_at: str,
) -> list[dict[str, str]]:
    sentence_ids = _json_list(chunk.get("sentence_ids", ""), "sentence_ids")
    sentences = _json_list(chunk.get("sentences_json", ""), "sentences_json")
    if len(sentence_ids) != len(sentences):
        raise ValueError("sentence_ids and sentences_json have different lengths")

    index_by_id = {sentence_id: index for index, sentence_id in enumerate(sentence_ids)}
    output = []
    seen = set()
    for span in response.get("spans") or []:
        start_id = str(span.get("start_sentence_id", "") or "").strip()
        end_id = str(span.get("end_sentence_id", "") or "").strip()
        if start_id not in index_by_id or end_id not in index_by_id:
            continue
        start = index_by_id[start_id]
        end = index_by_id[end_id]
        if start > end:
            continue
        key = span_key(str(chunk.get("article_id", "")), start_id, end_id)
        if key in seen:
            continue
        seen.add(key)
        claim_span_id = stable_span_id(key)
        evidence_ids = sentence_ids[start : end + 1]
        original_text = " ".join(sentences[start : end + 1]).strip()
        prev_sentence = (
            sentences[start - 1]
            if start > 0
            else str(chunk.get("prev_sentence", "") or "").strip()
        )
        next_sentence = (
            sentences[end + 1]
            if end + 1 < len(sentences)
            else str(chunk.get("next_sentence", "") or "").strip()
        )
        output.append(
            {
                "claim_id": f"{chunk.get('article_id', '')}-{claim_span_id}",
                "claim_span_id": claim_span_id,
                "article_id": str(chunk.get("article_id", "") or "").strip(),
                "chunk_id": str(chunk.get("chunk_id", "") or "").strip(),
                "title": str(chunk.get("title", "") or "").strip(),
                "date": str(chunk.get("date", "") or "").strip(),
                "url": str(chunk.get("url", "") or "").strip(),
                "claim_text": original_text,
                "detected_claim_text": str(span.get("claim_text", "") or "").strip(),
                "prev_sentence": prev_sentence,
                "next_sentence": next_sentence,
                "evidence_sentence_ids": json.dumps(
                    evidence_ids, ensure_ascii=False
                ),
                "span_start_sentence_id": start_id,
                "span_end_sentence_id": end_id,
                "claim_span_type": str(span.get("claim_type", "") or "").strip(),
                "is_claim": "True",
                "is_claim_reason": str(span.get("reason", "") or "").strip(),
                "is_claim_confidence": str(
                    span.get("confidence", "") or ""
                ).strip(),
                "is_claim_method": "hcx_span",
                "extraction_model": model,
                "prompt_version": PROMPT_VERSION,
                "extracted_at": extracted_at,
            }
        )
    return output


def call_hcx(api_key: str, model: str, chunk: dict[str, str], retries: int = 4) -> dict:
    prompt = USER_TEMPLATE.format(
        title=chunk.get("title") or "-",
        date=chunk.get("date") or "-",
        prev_sentence=chunk.get("prev_sentence") or "-",
        chunk_text=chunk.get("chunk_text") or "-",
        next_sentence=chunk.get("next_sentence") or "-",
    )
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "topP": 0.8,
        "seed": 42,
    }
    if model.startswith("HCX-007"):
        body["thinking"] = {"effort": "none"}
        body["maxCompletionTokens"] = 1600
        body["responseFormat"] = {"type": "json", "schema": RESPONSE_SCHEMA}
    else:
        body["maxTokens"] = 1600
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    for attempt in range(retries):
        response = requests.post(
            URL.format(model=model),
            headers=headers,
            json=body,
            timeout=120,
        )
        if response.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        response.raise_for_status()
        content = response.json()["result"]["message"]["content"]
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError("HCX response did not contain JSON")
        return json.loads(match.group())
    raise RuntimeError("HCX rate-limit retry count exceeded")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(
    path: Path,
    rows: list[dict[str, str]],
    fields: list[str],
    mode: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if mode == "w":
            writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Detect broad quantitative claim spans without KOSIS gating."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--progress-output", type=Path)
    parser.add_argument("--model", default="HCX-007")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.input.is_file():
        raise SystemExit(f"input CSV not found: {args.input}")
    progress_path = args.progress_output or args.output.with_name(
        f"{args.output.stem}_progress.csv"
    )

    load_dotenv()
    api_key = os.getenv("CLOVA_API_KEY")
    if not api_key:
        raise SystemExit(".env 에 CLOVA_API_KEY 를 설정하세요")

    chunks = read_csv(args.input)
    required = {"chunk_id", "article_id", "sentence_ids", "sentences_json", "chunk_text"}
    if chunks:
        missing = required - set(chunks[0])
        if missing:
            raise SystemExit(f"missing required chunk columns: {sorted(missing)}")

    existing_rows = (
        read_csv(args.output) if args.output.exists() and not args.overwrite else []
    )
    progress_rows = (
        read_csv(progress_path)
        if progress_path.exists() and not args.overwrite
        else []
    )
    done = {row.get("chunk_id", "") for row in progress_rows}
    known_keys = {
        span_key(
            row.get("article_id", ""),
            row.get("span_start_sentence_id", ""),
            row.get("span_end_sentence_id", ""),
        )
        for row in existing_rows
    }
    output_mode = "a" if args.output.exists() and not args.overwrite else "w"
    progress_mode = "a" if progress_path.exists() and not args.overwrite else "w"
    if output_mode == "w":
        write_rows(args.output, [], OUTPUT_COLUMNS, "w")
        output_mode = "a"
    if progress_mode == "w":
        write_rows(progress_path, [], PROGRESS_COLUMNS, "w")
        progress_mode = "a"

    processed = 0
    new_spans = 0
    today = time.strftime("%Y-%m-%d")
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id", "") or "").strip()
        if not chunk_id or chunk_id in done:
            continue
        if args.limit and processed >= args.limit:
            break
        try:
            response = call_hcx(api_key, args.model, chunk)
            rows = build_span_rows(chunk, response, args.model, today)
            unique_rows = []
            for row in rows:
                key = span_key(
                    row["article_id"],
                    row["span_start_sentence_id"],
                    row["span_end_sentence_id"],
                )
                if key not in known_keys:
                    known_keys.add(key)
                    unique_rows.append(row)
            write_rows(args.output, unique_rows, OUTPUT_COLUMNS, output_mode)
            write_rows(
                progress_path,
                [
                    {
                        "chunk_id": chunk_id,
                        "span_count": str(len(rows)),
                        "processed_at": today,
                    }
                ],
                PROGRESS_COLUMNS,
                progress_mode,
            )
            done.add(chunk_id)
            new_spans += len(unique_rows)
            print(
                f"[{chunk_id}] spans={len(rows)} new={len(unique_rows)}",
                flush=True,
            )
        except Exception as error:
            print(
                f"[{chunk_id}] failed: {type(error).__name__}: {error}",
                flush=True,
            )
        processed += 1
        time.sleep(args.sleep)

    print(
        f"completed_chunks={len(done)} processed_now={processed} "
        f"new_spans={new_spans} output={args.output}"
    )


if __name__ == "__main__":
    main()
