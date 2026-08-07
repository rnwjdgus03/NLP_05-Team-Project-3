#!/usr/bin/env python3
"""Blindly slice rows 251-300 and build the holdout6 Colab input bundle."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "archive" / "검증대상_기사드랍후.csv"
ARTICLES = ROOT / "data" / "holdout6_articles.csv"
ARTICLE_MANIFEST = ROOT / "data" / "holdout6_articles_manifest.json"
NOTEBOOK_TEMPLATE = ROOT / "notebooks" / "holdout5_201_250_gpu_colab.ipynb"
NOTEBOOK = ROOT / "notebooks" / "holdout6_251_300_gpu_colab.ipynb"
OUTPUT_DIR = ROOT / "outputs" / "holdout6_251_300"
STAGE = OUTPUT_DIR / "colab_bundle_stage"
BUNDLE = OUTPUT_DIR / "holdout6_colab_input_bundle.zip"
PREREGISTRATION = ROOT / "docs" / "홀드아웃6_사전등록_20260807.md"

START_ROW = 251
END_ROW = 300
ARTICLE_COLUMNS = ("기사제목", "작성일", "URL", "기사 본문(정제)", "검색 구분 레이블")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8",
    ).strip()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )


def build_article_slice() -> dict[str, object]:
    with SOURCE.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) < END_ROW:
        raise RuntimeError(f"원본 행 부족: {len(rows)} < {END_ROW}")
    selected = rows[START_ROW - 1:END_ROW]
    if len(selected) != 50 or len({row.get("URL", "") for row in selected}) != 50:
        raise RuntimeError("홀드아웃6은 URL이 서로 다른 50개 기사여야 한다")
    missing = [column for column in ARTICLE_COLUMNS if column not in (selected[0] if selected else {})]
    if missing:
        raise RuntimeError(f"원본 필수 열 누락: {missing}")
    with ARTICLES.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ARTICLE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(selected)
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": sha256(SOURCE),
        "source_row_count": len(rows),
        "slice_start_1_based": START_ROW,
        "slice_end_1_based": END_ROW,
        "row_count": len(selected),
        "columns": list(ARTICLE_COLUMNS),
        "output": str(ARTICLES.relative_to(ROOT)).replace("\\", "/"),
        "output_sha256": sha256(ARTICLES),
        "article_content_printed": False,
    }
    write_json(ARTICLE_MANIFEST, manifest)
    return manifest


def replace_holdout_labels(text: str) -> str:
    replacements = (
        ("holdout5", "holdout6"),
        ("홀드아웃5", "홀드아웃6"),
        ("201~250", "251~300"),
        ("201_250", "251_300"),
        ("kosis_meta_chroma_holdout5", "kosis_meta_chroma_holdout6"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def code_cell(source: str) -> dict[str, object]:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def build_notebook() -> None:
    notebook = json.loads(NOTEBOOK_TEMPLATE.read_text(encoding="utf-8-sig"))
    for cell in notebook["cells"]:
        cell["source"] = [replace_holdout_labels(line) for line in cell.get("source", [])]

    intro = "".join(notebook["cells"][0]["source"])
    intro = intro.replace(
        "로컬에서 완료한 KSS/HCX 주장 구간(50개 기사, 834문장, 203개 주장)을 입력으로 사용한다.",
        "아직 보지 않은 원본 기사 50개부터 KSS·HCX·BGE·Chroma·KOSIS 검증을 새로 실행한다.",
    )
    notebook["cells"][0]["source"] = intro.splitlines(keepends=True)

    verification = """# 5. 번들 해시와 고정 입력 검증
import csv, hashlib, json
manifest = json.loads((ROOT / 'bundle_manifest.json').read_text(encoding='utf-8-sig'))
for rel, expected in manifest['files'].items():
    actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
    assert actual == expected, f'해시 불일치: {rel}'
def csv_rows(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))
articles = csv_rows(ROOT / 'data' / 'holdout6_articles.csv')
assert len(articles) == 50
assert len({r['URL'] for r in articles}) == 50
assert not (ROOT / '.env').exists(), '번들에 .env가 들어 있으면 중단'
print('입력 검증 완료:', len(articles), '기사')
"""
    for cell in notebook["cells"]:
        if "# 5. 번들 해시와 고정 입력 검증" in "".join(cell.get("source", [])):
            cell["source"] = verification.splitlines(keepends=True)
            break
    else:
        raise RuntimeError("노트북에서 입력 검증 셀을 찾지 못했다")

    preprocess = """# 7. 기사부터 claim context까지 새로 생성 (HCX API, 재개 가능)
run([sys.executable, 'run_contextual_news_kosis_pipeline.py',
     '--articles', ROOT / 'data' / 'holdout6_articles.csv',
     '--table-index', ROOT / 'data/reference/kosis_table_summary.csv',
     '--semantic-index', SEM, '--out-dir', OUT,
     '--article-prefix', 'H6', '--device', 'cuda',
     '--chunk-size', '8', '--overlap', '2', '--lead-sentences', '3',
     '--local-window', '3', '--related-limit', '3',
     '--model', 'HCX-007', '--sleep', '0.5', '--stop-after', 'contexts'])
sentences = csv_rows(OUT / '01_sentences.csv')
contexts = csv_rows(OUT / '03_claim_contexts.csv')
assert len({r['article_id'] for r in sentences}) == 50
assert all(r['article_id'].startswith('H6') for r in sentences)
print('전처리 완료:', len(sentences), '문장 /', len(contexts), '주장')
"""
    bge_index = next(
        index for index, cell in enumerate(notebook["cells"])
        if "# 6. KOSIS 표" in "".join(cell.get("source", []))
    )
    notebook["cells"].insert(bge_index + 1, code_cell(preprocess))

    summary_marker = "'articles': 50, 'sentences': 834, 'claim_contexts': 203,"
    summary_replacement = (
        "'articles': len(articles), 'sentences': len(sentences), "
        "'claim_contexts': len(contexts),"
    )
    for cell in notebook["cells"]:
        source = "".join(cell.get("source", []))
        if summary_marker in source:
            cell["source"] = source.replace(summary_marker, summary_replacement).splitlines(keepends=True)

    NOTEBOOK.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


def bundle_paths() -> list[Path]:
    root_python = [
        ROOT / path
        for path in git("ls-files", "*.py").splitlines()
        if path and "/" not in path and "\\" not in path
    ]
    required = [
        ROOT / "requirements.txt",
        ROOT / "requirements-ml.txt",
        ARTICLES,
        ARTICLE_MANIFEST,
        ROOT / "data" / "seed_region_codes.csv",
        ROOT / "data" / "reference" / "kosis_table_summary.csv",
        PREREGISTRATION,
        ROOT / "docs" / "홀드아웃_50건_프로토콜.md",
    ]
    paths = sorted({path.resolve() for path in [*root_python, *required]})
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"번들 파일 누락: {missing}")
    return paths


def build_bundle() -> dict[str, object]:
    if STAGE.exists() or BUNDLE.exists():
        raise RuntimeError(
            f"기존 홀드아웃6 번들이 있다. 재생성하려면 먼저 명시적으로 치운다: {OUTPUT_DIR}"
        )
    STAGE.mkdir(parents=True)
    files: dict[str, str] = {}
    for source in bundle_paths():
        relative = source.relative_to(ROOT)
        target = STAGE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        files[relative.as_posix()] = sha256(target)
    source_commit = git("rev-parse", "HEAD")
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "source_commit": source_commit,
        "working_tree_code_hashes_authoritative": True,
        "preregistration": "docs/홀드아웃6_사전등록_20260807.md",
        "secrets_included": False,
        "expected": {"articles": 50, "source_rows": [START_ROW, END_ROW]},
        "files": dict(sorted(files.items())),
    }
    write_json(STAGE / "bundle_manifest.json", manifest)
    with zipfile.ZipFile(BUNDLE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(STAGE).as_posix())
    manifest["bundle_sha256"] = sha256(BUNDLE)
    manifest["bundle_size_bytes"] = BUNDLE.stat().st_size
    return manifest


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    article_manifest = build_article_slice()
    build_notebook()
    bundle_manifest = build_bundle()
    print(f"articles={article_manifest['row_count']} rows={START_ROW}-{END_ROW}")
    print(f"articles_sha256={article_manifest['output_sha256']}")
    print(f"bundle={BUNDLE}")
    print(f"bundle_sha256={bundle_manifest['bundle_sha256']}")
    print(f"bundle_size_bytes={bundle_manifest['bundle_size_bytes']}")


if __name__ == "__main__":
    main()
