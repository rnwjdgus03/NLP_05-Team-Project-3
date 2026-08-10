#!/usr/bin/env python3
"""Build holdout8 v6 Colab packet with retrieval/gate/period/rerank fixes."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "notebooks/holdout8_stratified48_v5_gpu_colab.ipynb"
NOTEBOOK = ROOT / "notebooks/holdout8_stratified48_v6_gpu_colab.ipynb"
ARTICLES = ROOT / "data/holdout8_stratified_articles.csv"
ASSIGNMENTS = ROOT / "data/holdout8_stratified_assignments.csv"
SOURCE_MANIFEST = ROOT / "data/holdout8_stratified_manifest.json"
PREREG = ROOT / "docs/홀드아웃8_v6_사전등록_20260808.md"
OUTPUT_DIR = ROOT / "outputs/holdout8_stratified48_v6"
BUNDLE = OUTPUT_DIR / "holdout8_v6_colab_input_bundle.zip"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_notebook() -> None:
    notebook = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    replacements = (
        ("stratified48_v5", "stratified48_v6"),
        ("holdout8_v5_colab_input_bundle.zip", "holdout8_v6_colab_input_bundle.zip"),
        ("holdout8_v5_gpu_results.zip", "holdout8_v6_gpu_results.zip"),
        ("holdout8_v5_gpu_results", "holdout8_v6_gpu_results"),
        ("mcp_gold_200_coordinate_ab_gpu_results_v5", "mcp_gold_200_coordinate_ab_gpu_results_v6"),
        ("# 12. v5 blind", "# 12. v6 blind"),
        ("EVAL_V4", "EVAL_V6"),
        ("evaluation_set_v4_enriched.csv", "evaluation_set_v6_enriched.csv"),
        ("v4_enrichment_stats.json", "v6_enrichment_stats.json"),
        ("v4_coordinate_ab_summary.json", "v6_coordinate_ab_summary.json"),
        ("v4_blind_ab_summary.json", "v6_blind_ab_summary.json"),
        ("'v4_blind_ab':", "'v6_blind_ab':"),
        ("v4_ab", "v6_ab"),
        ("'--item-top-k', '3'", "'--item-top-k', '10'"),
    )
    for cell in notebook["cells"]:
        source = "".join(cell.get("source", []))
        for old, new in replacements:
            source = source.replace(old, new)
        if source.startswith("# 13. KOSIS 좌표 검증"):
            source = """# 13. ITEM·OBJ 우선 선택 좌표 검증 — Top-5/Top-10 각각 재시도
import time
VALID5 = MAP / 'chroma_validated_top5.csv'
VALID10 = MAP / 'chroma_validated_top10.csv'

def validate_selected(selected, output):
    for attempt in range(1, 6):
        run([sys.executable, 'kosis_validate_mapping_candidates.py',
             '--input', selected, '--meta-index', META, '--output', output,
             '--evaluate-all-ranks', '--strict-seeded-coordinate',
             '--item-top-k', '1', '--obj-top-k', '1',
             '--max-combinations', '1', '--allow-provisional'])
        rows = csv_rows(output)
        api_errors = sum(r.get('mapping_status') == 'API_ERROR' for r in rows)
        print(f'{selected.name} attempt={attempt} API_ERROR rows={api_errors}')
        if api_errors == 0:
            return rows
        time.sleep(20)
    raise AssertionError(f'{selected.name}: API_ERROR가 남았습니다. 이 셀을 다시 실행하세요.')

validated5 = validate_selected(SELECT5, VALID5)
validated10 = validate_selected(SELECT10, VALID10)
VALID = VALID5  # 이후 실제값 판정의 기본 arm; 두 arm 파일은 모두 결과 ZIP에 보존
print('validated top5/top10 =', len(validated5), len(validated10))
"""
        cell["source"] = source.splitlines(keepends=True)
    NOTEBOOK.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def write_prereg() -> None:
    source_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8-sig"))
    PREREG.write_text(
        f"""# 홀드아웃8 v6 사전등록 — 검색·게이트·기간·좌표 재순위 개선

- 잠금 시각: `{datetime.now().astimezone().isoformat()}`
- 기사 수: `48` (국가/연령/성별/품목 각 12)
- 기사 입력 SHA-256: `{source_manifest['articles_sha256']}`
- v5와 기사 집합 동일: `true`
- 결과를 본 뒤 정답 규칙 수정: `false`

## v6 고정 변경

1. KOSIS 표 lexical/BGE/reranker 쿼리에 기사에 명시된 조사명과 국가·지역·연령·성별·품목 대상 축을 포함한다.
2. 증감률(rate_change)은 직접 공표 ITEM 확인 또는 수준값 재계산 전까지 READY에서 제외하고 ENRICH로 보낸다.
3. ISO 날짜와 Excel 일련번호 날짜를 모두 해석해 `작년 12월`, `지난 2월`, `지난달`을 월 좌표로 보존한다.
4. `지난 2월 … 지난해 같은 달`은 대상 월과 비교 월을 각각 보존한다.
5. 좌표 선택은 최초 표에 고정하지 않고 전체 후보에서 ITEM 일치 → OBJ 대상 일치 → 검색 점수 순으로 선택한다.
6. 표 Top-5/Top-10 A/B는 동일 measurement, 동일 KOSIS 메타 인덱스, ITEM 후보 최대 10개로 비교한다.
7. KOSIS MCP 실제 조회로 확정된 자동 골드만 정확도 분모에 포함한다.
""",
        encoding="utf-8",
    )


def build_bundle() -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    required = [
        ROOT / "requirements.txt",
        ROOT / "requirements-ml.txt",
        ARTICLES,
        ASSIGNMENTS,
        SOURCE_MANIFEST,
        PREREG,
        ROOT / "data/seed_region_codes.csv",
        ROOT / "data/reference/kosis_table_summary.csv",
    ]
    sources = sorted({path.resolve() for path in [*ROOT.glob("*.py"), *required]})
    missing = [path for path in sources if not path.is_file()]
    if missing:
        raise RuntimeError(f"bundle files missing: {missing}")
    files = {path.relative_to(ROOT).as_posix(): sha256(path) for path in sources}
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "purpose": "holdout8 v6 survey+axis retrieval, derived gate, relative-month, ITEM/OBJ-first rerank",
        "secrets_included": False,
        "expected": {
            "articles": 48,
            "strata": {"country": 12, "age": 12, "gender": 12, "product": 12},
            "prior_url_overlap": 0,
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
    build_notebook()
    write_prereg()
    manifest = build_bundle()
    print(f"notebook={NOTEBOOK}")
    print(f"bundle={BUNDLE}")
    print(f"bundle_size={manifest['bundle_size_bytes']}")
    print(f"bundle_sha256={manifest['bundle_sha256']}")


if __name__ == "__main__":
    main()
