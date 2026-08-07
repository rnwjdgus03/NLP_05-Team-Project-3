#!/usr/bin/env python3
"""Lock 50 URL-disjoint unseen articles and build the holdout7 v4 Colab packet."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/archive/검증대상_기사드랍후.csv"
ARTICLES = ROOT / "data/holdout7_disjoint_articles.csv"
MANIFEST = ROOT / "data/holdout7_disjoint_manifest.json"
TEMPLATE = ROOT / "notebooks/holdout6_251_300_gpu_colab.ipynb"
NOTEBOOK = ROOT / "notebooks/holdout7_disjoint50_v4_gpu_colab.ipynb"
PREREG = ROOT / "docs/홀드아웃7_v4_사전등록_20260807.md"
OUTPUT_DIR = ROOT / "outputs/holdout7_disjoint50_v4"
BUNDLE = OUTPUT_DIR / "holdout7_v4_colab_input_bundle.zip"
START_ROW, SELECT_COUNT = 301, 50
EXCLUSION_SOURCES = (
    (ROOT / "data/gold/mcp_full_gold_200.csv", "url"),
    (ROOT / "data/holdout5_articles.csv", "URL"),
    (ROOT / "data/holdout6_articles.csv", "URL"),
)
ARTICLE_COLUMNS = ("기사제목", "작성일", "URL", "기사 본문(정제)", "검색 구분 레이블")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")


def lock_articles() -> dict[str, object]:
    with SOURCE.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    excluded_urls: set[str] = set()
    exclusion_counts: dict[str, int] = {}
    for path, url_field in EXCLUSION_SOURCES:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            urls = {row.get(url_field, "").strip() for row in csv.DictReader(handle)}
        urls.discard("")
        excluded_urls.update(urls)
        exclusion_counts[path.relative_to(ROOT).as_posix()] = len(urls)

    selected: list[dict[str, str]] = []
    selected_row_numbers: list[int] = []
    selected_urls: set[str] = set()
    skipped_excluded = 0
    skipped_duplicate = 0
    for row_number, row in enumerate(rows[START_ROW - 1 :], start=START_ROW):
        url = row.get("URL", "").strip()
        if not url or url in excluded_urls:
            skipped_excluded += 1
            continue
        if url in selected_urls:
            skipped_duplicate += 1
            continue
        selected.append(row)
        selected_row_numbers.append(row_number)
        selected_urls.add(url)
        if len(selected) == SELECT_COUNT:
            break

    if len(selected) != SELECT_COUNT or len(selected_urls) != SELECT_COUNT:
        raise RuntimeError("holdout7 must contain 50 distinct article URLs")
    missing = [field for field in ARTICLE_COLUMNS if field not in selected[0]]
    if missing:
        raise RuntimeError(f"source columns missing: {missing}")
    with ARTICLES.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ARTICLE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(selected)
    payload = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": sha256(SOURCE),
        "source_row_count": len(rows),
        "selection_start_1_based": START_ROW,
        "selection_end_1_based": selected_row_numbers[-1],
        "source_row_numbers_1_based": selected_row_numbers,
        "row_count": len(selected),
        "columns": list(ARTICLE_COLUMNS),
        "output": ARTICLES.relative_to(ROOT).as_posix(),
        "output_sha256": sha256(ARTICLES),
        "article_content_printed": False,
        "excluded_url_sources": exclusion_counts,
        "skipped_excluded_or_blank": skipped_excluded,
        "skipped_duplicate": skipped_duplicate,
        "development_gold_overlap": len(selected_urls & excluded_urls),
        "rules_frozen_before_content_review": True,
    }
    write_json(MANIFEST, payload)
    return payload


def replacement_map() -> tuple[tuple[str, str], ...]:
    return (
        ("홀드아웃6", "홀드아웃7"), ("holdout6", "holdout7"),
        ("251~300", "disjoint 50"), ("251_300", "disjoint50_v4"),
        ("H6", "H7"), ("kosis_meta_chroma_holdout6", "kosis_meta_chroma_holdout7"),
    )


def replace_all(text: str) -> str:
    for old, new in replacement_map():
        text = text.replace(old, new)
    return text


def build_notebook() -> None:
    notebook = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        source = replace_all("".join(cell.get("source", [])))
        source = source.replace("holdout7_articles.csv", "holdout7_disjoint_articles.csv")
        cell["source"] = source.splitlines(keepends=True)

    target_cell = notebook["cells"][13]
    source = """# 12. v4 blind Top-5/Top-10 coordinate A/B and two-stage audit
EVAL_V4 = MAP / 'evaluation_set_v4_enriched.csv'
run([sys.executable, 'enrich_mcp_gold_200_inputs.py',
     '--input', EVAL, '--output', EVAL_V4,
     '--stats', MAP / 'v4_enrichment_stats.json'])

CAND = MAP / 'chroma_candidates_top5.csv'
CAND10 = MAP / 'chroma_candidates_top10.csv'
for table_k, output, stats in [
    ('5', CAND, MAP / 'chroma_stats_top5.csv'),
    ('10', CAND10, MAP / 'chroma_stats_top10.csv'),
]:
    run([sys.executable, 'kosis_chroma_hybrid_search.py',
         '--claims', EVAL_V4, '--table-candidates', TABLE_CAND,
         '--persist-dir', CHR, '--collection', 'kosis_meta_coordinates',
         '--output', output, '--stats-output', stats,
         '--table-top-k', table_k,
         '--dense-top-k', '50', '--lexical-top-k', '50',
         '--rerank-top-k', '20', '--final-top-k', '10',
         '--reranker-model', 'BAAI/bge-reranker-v2-m3', '--device', 'cuda'])

SELECT5 = MAP / 'two_stage_selected_top5.csv'
SELECT10 = MAP / 'two_stage_selected_top10.csv'
for candidates, selected in [(CAND, SELECT5), (CAND10, SELECT10)]:
    run([sys.executable, 'select_mcp_gold_200_two_stage_coordinates.py',
         '--claims', EVAL_V4, '--candidates', candidates,
         '--output', selected, '--item-top-k', '3'])

def selected_key(row):
    return '|'.join(str(row.get(field, '')) for field in (
        'org_id', 'tbl_id', 'selected_itm_id', 'selected_obj_l1', 'selected_obj_l2'))
s5 = {r.get('claim_measurement_id') or r.get('claim_id'): selected_key(r) for r in csv_rows(SELECT5)}
s10 = {r.get('claim_measurement_id') or r.get('claim_id'): selected_key(r) for r in csv_rows(SELECT10)}
common = set(s5) & set(s10)
v4_ab = {
    'top5_selected': len(s5), 'top10_selected': len(s10), 'common': len(common),
    'selection_agreement': (sum(s5[k] == s10[k] for k in common) / len(common)) if common else None,
    'top5_obj_target_matched': sum(r.get('two_stage_obj_matched') == 'Y' for r in csv_rows(SELECT5)),
    'top10_obj_target_matched': sum(r.get('two_stage_obj_matched') == 'Y' for r in csv_rows(SELECT10)),
}
(MAP / 'v4_blind_ab_summary.json').write_text(json.dumps(v4_ab, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(v4_ab, ensure_ascii=False, indent=2))
"""
    target_cell["source"] = source.splitlines(keepends=True)

    final_source = "".join(notebook["cells"][17]["source"])
    final_source = final_source.replace(
        "'verdict_codes': dict(codes), 'api_error_rows': 0,",
        "'verdict_codes': dict(codes), 'api_error_rows': 0, 'v4_blind_ab': v4_ab,",
    ).replace("/content/holdout7_gpu_results", "/content/holdout7_v4_gpu_results")
    notebook["cells"][17]["source"] = final_source.splitlines(keepends=True)
    NOTEBOOK.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def write_prereg(manifest: dict[str, object]) -> None:
    PREREG.write_text(
        f"""# 홀드아웃7 v4 사전등록 — URL 비중복 50건

- 잠금 시각: `{manifest['created_at']}`
- 검색 시작 행: `{START_ROW}`
- 마지막 선택 행: `{manifest['selection_end_1_based']}`
- 기사 수: `50`
- 입력 SHA-256: `{manifest['output_sha256']}`
- 개발 골드 200과 행 중복: `0`
- 규칙 동결 후 기사 내용 미열람: `true`

## 고정 비교

1. 동일 표 후보에서 좌표 `table_top_k=5`와 `10`을 비교한다.
2. ITEM을 먼저 선택하고 같은 표 안에서 OBJ를 선택한다.
3. 국가·연령·성별·품목 대상이 있으면 집계 OBJ보다 직접 일치 OBJ를 우선한다.
4. 정답 골드가 없는 블라인드 단계에서는 선택 안정성, OBJ target 일치, READY/API 오류를 보고한다.
5. 정확도 판정은 결과 생성 후 별도 MCP/사람 라벨을 잠가 수행한다.
""",
        encoding="utf-8",
    )


def build_bundle(article_manifest: dict[str, object]) -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    required = [
        ROOT / "requirements.txt", ROOT / "requirements-ml.txt", ARTICLES, MANIFEST, PREREG,
        ROOT / "data/seed_region_codes.csv", ROOT / "data/reference/kosis_table_summary.csv",
    ]
    sources = sorted({path.resolve() for path in [*ROOT.glob("*.py"), *required]})
    missing = [path for path in sources if not path.is_file()]
    if missing:
        raise RuntimeError(f"bundle files missing: {missing}")
    files = {path.relative_to(ROOT).as_posix(): sha256(path) for path in sources}
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "purpose": "unseen holdout7 v4 Top-5/Top-10 ITEM-OBJ audit",
        "secrets_included": False,
        "expected": {
            "articles": SELECT_COUNT,
            "selection_start_row": START_ROW,
            "selection_end_row": article_manifest["selection_end_1_based"],
            "development_and_prior_holdout_url_overlap": 0,
        },
        "files": files,
    }
    with zipfile.ZipFile(BUNDLE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sources:
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr("bundle_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    manifest["bundle_sha256"] = sha256(BUNDLE)
    manifest["bundle_size_bytes"] = BUNDLE.stat().st_size
    return manifest


def main() -> None:
    article_manifest = lock_articles()
    write_prereg(article_manifest)
    build_notebook()
    bundle_manifest = build_bundle(article_manifest)
    print(f"articles=50 rows={START_ROW}-{article_manifest['selection_end_1_based']}")
    print(f"articles_sha256={article_manifest['output_sha256']}")
    print(f"notebook={NOTEBOOK}")
    print(f"bundle={BUNDLE}")
    print(f"bundle_sha256={bundle_manifest['bundle_sha256']}")


if __name__ == "__main__":
    main()
