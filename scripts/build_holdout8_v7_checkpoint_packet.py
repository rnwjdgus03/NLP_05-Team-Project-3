#!/usr/bin/env python3
"""Build a v7 Colab rerun packet reusing the v6 HCX checkpoints."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "notebooks/holdout8_stratified48_v6_gpu_colab.ipynb"
NOTEBOOK = ROOT / "notebooks/holdout8_stratified48_v7_checkpoint_gpu_colab.ipynb"
V6 = ROOT / "outputs/holdout8_stratified48_v6/gpu_results_20260809/extracted"
PREREG = ROOT / "docs/홀드아웃8_v7_체크포인트_사전등록_20260809.md"
OUTPUT_DIR = ROOT / "outputs/holdout8_stratified48_v7"
BUNDLE = OUTPUT_DIR / "holdout8_v7_checkpoint_colab_input_bundle.zip"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_notebook() -> None:
    notebook = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    replacements = (
        ("stratified48_v6", "stratified48_v7"),
        ("holdout8_v6_colab_input_bundle.zip", "holdout8_v7_checkpoint_colab_input_bundle.zip"),
        ("holdout8_v6_gpu_results", "holdout8_v7_gpu_results"),
        ("EVAL_V6", "EVAL_V7"),
        ("evaluation_set_v6_enriched.csv", "evaluation_set_v7_enriched.csv"),
        ("v6_enrichment_stats.json", "v7_enrichment_stats.json"),
        ("v6_blind_ab_summary.json", "v7_blind_ab_summary.json"),
        ("v6_ab", "v7_ab"),
        ("'v6_blind_ab':", "'v7_blind_ab':"),
        ("# 12. v6 blind", "# 12. v7 real Top-5/Top-10"),
    )
    for cell in notebook["cells"]:
        source = "".join(cell.get("source", []))
        for old, new in replacements:
            source = source.replace(old, new)
        source = source.replace(
            "ROOT = Path('/content/holdout8_gpu')",
            "ROOT = Path('/content/holdout8_gpu_v7')",
        )
        source = source.replace(
            "SEM = ROOT / 'data' / 'indexes' / 'kosis_bge_m3'",
            "OLD_SEM = Path('/content/holdout8_gpu/data/indexes/kosis_bge_m3')\n"
            "SEM = OLD_SEM if (OLD_SEM / 'manifest.json').exists() else ROOT / 'data' / 'indexes' / 'kosis_bge_m3'",
        )
        source = source.replace(
            "kosis_meta_chroma_holdout8",
            "kosis_meta_chroma_holdout8_v7",
        )
        if source.startswith("# 4. 원본 기사"):
            source = """# 4. 원본 기사 잠금 확인
import csv
def csv_rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))

ARTICLES = ROOT / 'data' / 'holdout8_stratified_articles.csv'
articles = csv_rows(ARTICLES)
assert len(articles) == 48
print('articles =', len(articles))
"""
        elif source.startswith("# 5. 문장"):
            source = """# 5. v6 문장 체크포인트 재사용
checkpoint = ROOT / 'data/checkpoints/01_sentences.csv'
target = OUT / '01_sentences.csv'
shutil.copy2(checkpoint, target)
sentences = csv_rows(target)
print('sentence checkpoint rows =', len(sentences))
"""
        elif source.startswith("# 7. claim"):
            source = """# 7. v6 claim-context 체크포인트 재사용
checkpoint = ROOT / 'data/checkpoints/03_claim_contexts.csv'
target = OUT / '03_claim_contexts.csv'
shutil.copy2(checkpoint, target)
contexts = csv_rows(target)
print('claim-context checkpoint rows =', len(contexts))
"""
        elif source.startswith("# 8. HCX-007"):
            source = """# 8. v6 HCX measurement 체크포인트 재사용 — API 재호출 없음
checkpoint = ROOT / 'data/checkpoints/05_hcx_measurements.csv'
target = OUT / '05_hcx_measurements.csv'
shutil.copy2(checkpoint, target)
measurements = csv_rows(target)
print('measurement checkpoint rows =', len(measurements))
"""
        elif source.startswith("# 9. measurement"):
            source = source.replace(
                "     '--rerank-top-k', '20', '--device', 'cuda'])",
                "     '--rerank-top-k', '20', '--top-tables', '10',\n"
                "     '--top-rank-for-meta', '10', '--device', 'cuda'])",
            )
        cell["source"] = source.splitlines(keepends=True)
    NOTEBOOK.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def write_prereg() -> None:
    PREREG.write_text(
        f"""# 홀드아웃8 v7 체크포인트 재실행 사전등록

- 생성 시각: `{datetime.now().astimezone().isoformat()}`
- 기사·문장·claim-context·HCX measurement: v6 결과를 그대로 재사용
- HCX API 재호출: `false`
- v6 measurement 행 수: `769`
- 파생 증감률 READY 제외 규칙 유지

## 변경

1. 1차 표 후보를 5개가 아니라 10개 저장한다.
2. 공식 KOSIS 메타를 후보 순위 10위까지 구축한다.
3. Top-5와 Top-10 좌표 검색이 서로 다른 표 후보 풀을 사용한다.
4. 증감값은 `증감(전년동월)` ITEM을 `월평균임금`·`증감률`보다 우선한다.
5. `-`를 OBJ target에서 제외하고 `정규직`과 `비정규직`을 정확히 구분한다.
6. 기존 구조화 `measurement_role`·`value_type`을 enrichment에서 보존한다.
7. 조사월과 측정연도를 결합하고 조사명 속 월보다 `작년 한해` 대상을 우선한다.
8. 평가는 `claim_measurement_id`를 `claim_id`보다 먼저 매칭한다.
""",
        encoding="utf-8",
    )


def build_bundle() -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    archive_files: dict[str, Path] = {
        path.name: path for path in ROOT.glob("*.py")
    }
    for relative in (
        "requirements.txt", "requirements-ml.txt",
        "data/holdout8_stratified_articles.csv",
        "data/holdout8_stratified_assignments.csv",
        "data/holdout8_stratified_manifest.json",
        "data/seed_region_codes.csv",
        "data/reference/kosis_table_summary.csv",
    ):
        archive_files[relative] = ROOT / relative
    archive_files["docs/홀드아웃8_v7_체크포인트_사전등록_20260809.md"] = PREREG
    archive_files["data/checkpoints/01_sentences.csv"] = V6 / "01_sentences.csv"
    archive_files["data/checkpoints/03_claim_contexts.csv"] = V6 / "03_claim_contexts.csv"
    archive_files["data/checkpoints/05_hcx_measurements.csv"] = V6 / "05_hcx_measurements.csv"
    missing = [path for path in archive_files.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"bundle files missing: {missing}")
    files = {name: sha256(path) for name, path in archive_files.items()}
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "purpose": "holdout8 v7 real Top-5/Top-10 rerun from frozen v6 checkpoints",
        "secrets_included": False,
        "checkpoint_rows": {"sentences": 1054, "claim_contexts": 317, "measurements": 769},
        "files": files,
    }
    with zipfile.ZipFile(BUNDLE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(archive_files.items()):
            archive.write(path, name)
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
