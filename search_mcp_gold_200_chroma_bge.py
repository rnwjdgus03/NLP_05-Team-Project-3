#!/usr/bin/env python3
"""Search the real Chroma KOSIS table collection for the gold-200 inputs.

Only gold-free input fields are read. Gold coordinates and labels are never
used to form the query or rank candidates.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import re
from pathlib import Path

from kosis_semantic_search import SentenceTransformerEmbedder, build_claim_query


COUNTRY_TERMS = {
    "미국", "중국", "일본", "베트남", "홍콩", "대만", "싱가포르", "인도",
    "독일", "프랑스", "영국", "캐나다", "멕시코", "브라질", "러시아",
    "호주", "사우디", "아랍에미리트", "EU", "유럽연합",
}
UNIT_PATTERN = re.compile(
    r"([%％]\s*포인트|퍼센트\s*포인트|[%％]|억\s*달러|만\s*달러|천\s*달러|"
    r"조\s*원|억\s*원|만\s*원|천\s*원|달러|원|만\s*명|천\s*명|명|"
    r"만\s*가구|천\s*가구|가구|개월|만\s*개|천\s*개|개|"
    r"만\s*대|천\s*대|대|건|배|시간|년|월|일)"
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def infer_table_search_profile(claim: dict[str, str]) -> dict[str, tuple[str, ...]]:
    """Return general domain aliases without looking at gold coordinates."""

    text = " ".join(
        str(claim.get(key, "") or "") for key in ("title", "claim_text")
    )
    compact = "".join(text.split())
    aliases: list[str] = []
    negatives: list[str] = []
    if any(token in compact for token in ("수출", "수입", "무역수지")):
        country_scoped = (
            any(token in text for token in COUNTRY_TERMS)
            or any(token in compact for token in ("국가별", "대미", "대중", "대일"))
        )
        aliases.append(
            "국가별 수출액 수입액" if country_scoped else "품목별 수출액 수입액"
        )
        negatives.extend(("기업혁신조사", "수출액 수준", "수입액 수준", "전망", "설문"))
    if any(token in compact for token in ("출생아", "합계출산율", "자연증가")):
        aliases.append("출생아수 합계출산율 자연증가")
    if "농가" in compact and any(token in compact for token in ("농가인구", "농업인구", "시군구")):
        aliases.append("행정구역 시군구별 농가 농가인구")
    return {"aliases": tuple(aliases), "negative_terms": tuple(negatives)}


def _number_variants(value: str) -> list[str]:
    value = str(value or "").strip().replace(",", "")
    if not value:
        return []
    variants = [value]
    try:
        number = float(value)
    except ValueError:
        return variants
    if number.is_integer():
        variants.append(str(int(number)))
    variants.extend(v.replace("-", "+") for v in list(variants) if v.startswith("-"))
    return list(dict.fromkeys(variants))


def select_claim_unit(claim: dict[str, str]) -> str:
    """Select the unit attached to ``claim_value`` from the claim sentence."""

    text = str(claim.get("claim_text", "") or "")
    claim_type = str(claim.get("claim_type", "") or "").upper()
    candidates: list[tuple[int, int, str]] = []
    for variant in sorted(_number_variants(claim.get("claim_value", "")), key=len, reverse=True):
        escaped = re.escape(variant)
        escaped = escaped.replace(r"\.", r"[.,]").replace(r"\-", r"[-−]")
        for match in re.finditer(
            rf"(?<![0-9.])(?:\(?\s*){escaped}\s*{UNIT_PATTERN.pattern}",
            text,
            flags=re.IGNORECASE,
        ):
            unit = re.sub(r"\s+", " ", match.group(1)).strip().replace("％", "%")
            is_rate = "%" in unit or "포인트" in unit
            is_duration = unit in {"년", "월", "일", "개월", "시간"}
            score = 0
            if claim_type == "CHANGE_POINT" and "포인트" in unit:
                score += 140
            elif claim_type == "CHANGE_RATE" and is_rate:
                score += 120
            elif claim_type == "LEVEL" and not is_duration:
                score += 60
            if is_duration and claim_type in {"CHANGE_RATE", "CHANGE_POINT"}:
                score -= 80
            # Prefer the most specific numeric representation and, all else
            # equal, the later mention (news leads often contain date numbers).
            score += len(variant)
            candidates.append((score, match.start(), unit))
    if candidates:
        return max(candidates)[2]

    raw = str(claim.get("claim_unit", "") or "").strip()
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        parsed = None
    if isinstance(parsed, list):
        meaningful = [str(unit).strip() for unit in parsed if str(unit).strip()]
        if "RATE" in claim_type:
            for unit in meaningful:
                if "%" in unit or "포인트" in unit:
                    return unit
        for unit in meaningful:
            if unit not in {"년", "월", "일", "분"}:
                return unit
        return meaningful[0] if meaningful else ""
    return raw


def build_gold_free_table_query(claim: dict[str, str]) -> str:
    """Adapt the public gold-200 input schema to the shared search schema.

    The input fixture deliberately contains no ``gold_*`` fields.  Its column
    names nevertheless differ from the structured pipeline schema, so passing
    the row directly to ``build_claim_query`` used to discard the title,
    claim type, value, and unit.  Keep the adapter here so evaluation cannot
    accidentally consume answer coordinates.
    """

    forbidden = [
        key
        for key in claim
        if key.lower().startswith("gold_") and key.lower() != "gold_id"
    ]
    if forbidden:
        raise ValueError(
            "retrieval input must not contain gold fields: " + ", ".join(sorted(forbidden))
        )
    profile = infer_table_search_profile(claim)
    indicator = (
        claim.get("measurement_indicator")
        or claim.get("indicator")
        or claim.get("title", "")
    )
    adapted = {
        "indicator": indicator,
        "semantic_type": claim.get("semantic_type") or claim.get("claim_type", ""),
        "unit": select_claim_unit(claim),
        "period": claim.get("period", ""),
        "prd_se": claim.get("prd_se", ""),
        "claim_text": claim.get("claim_text", ""),
    }
    shared = build_claim_query(adapted)
    value = str(claim.get("claim_value", "") or "").strip()
    suffix = []
    title = str(claim.get("title", "") or "").strip()
    if title and title != indicator:
        suffix.append(f"title: {title}")
    if value:
        suffix.append(f"claim_value: {value}")
    if profile["aliases"]:
        suffix.append("preferred_table: " + "; ".join(profile["aliases"]))
    return " | ".join([shared, *suffix])


def main() -> None:
    parser = argparse.ArgumentParser(description="BGE-M3 search over Chroma kosis_table")
    parser.add_argument("--claims", default="data/gold/mcp_full_gold_200_inputs.csv")
    parser.add_argument("--persist-dir", default="data/indexes/kosis_table_chroma")
    parser.add_argument("--collection", default="kosis_table")
    parser.add_argument("--output", required=True)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    import chromadb

    persist_dir = Path(args.persist_dir)
    manifest = json.loads((persist_dir / "chroma_manifest.json").read_text(encoding="utf-8"))
    claims = read_csv(Path(args.claims))
    queries = [build_gold_free_table_query(row) for row in claims]
    embedder = SentenceTransformerEmbedder(manifest["embedding_model"], device=args.device)
    vectors = embedder.encode(queries, batch_size=args.batch_size, show_progress_bar=True)

    client = chromadb.PersistentClient(path=str(persist_dir))
    collection = client.get_collection(args.collection)
    result = collection.query(
        query_embeddings=vectors.tolist(),
        n_results=args.top_k,
        include=["documents", "metadatas", "distances"],
    )

    rows: list[dict[str, object]] = []
    for claim_index, claim in enumerate(claims):
        ids = result["ids"][claim_index]
        metadatas = result["metadatas"][claim_index]
        distances = result["distances"][claim_index]
        documents = result["documents"][claim_index]
        for rank, (candidate_id, metadata, distance, document) in enumerate(
            zip(ids, metadatas, distances, documents), 1
        ):
            metadata = metadata or {}
            rows.append(
                {
                    "gold_id": claim.get("gold_id", ""),
                    "claim_id": claim.get("claim_id", ""),
                    "article_id": claim.get("article_id", ""),
                    "claim_text": claim.get("claim_text", ""),
                    "input_quality_status": claim.get("input_quality_status", ""),
                    "input_quality_reason": claim.get("input_quality_reason", ""),
                    "candidate_rank": rank,
                    "org_id": metadata.get("org_id", ""),
                    "tbl_id": metadata.get("tbl_id", ""),
                    "tbl_name": metadata.get("tbl_name", ""),
                    "stat_id": metadata.get("stat_id", ""),
                    "category_path": metadata.get("category_path", ""),
                    "candidate_id": candidate_id,
                    "semantic_score": 1.0 - float(distance),
                    "retrieval_backend": "chroma+bge-m3",
                    "candidate_document": document,
                }
            )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"claims={len(claims)} candidates={len(rows)} output={output}", flush=True)


if __name__ == "__main__":
    main()
