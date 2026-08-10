#!/usr/bin/env python3
"""Build the stratified holdout8 v5 Colab notebook and input bundle."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "notebooks/holdout7_disjoint50_v4_gpu_colab.ipynb"
NOTEBOOK = ROOT / "notebooks/holdout8_stratified48_v5_gpu_colab.ipynb"
ARTICLES = ROOT / "data/holdout8_stratified_articles.csv"
ASSIGNMENTS = ROOT / "data/holdout8_stratified_assignments.csv"
SOURCE_MANIFEST = ROOT / "data/holdout8_stratified_manifest.json"
PREREG = ROOT / "docs/홀드아웃8_v5_사전등록_20260807.md"
OUTPUT_DIR = ROOT / "outputs/holdout8_stratified48_v5"
BUNDLE = OUTPUT_DIR / "holdout8_v5_colab_input_bundle.zip"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_notebook() -> None:
    notebook = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    replacements = (
        # 상세 경로를 일반 holdout 번호보다 먼저 바꿔야 한다. 순서가 뒤집히면
        # holdout7_disjoint_articles.csv가 holdout8_disjoint_articles.csv로 남는다.
        ("holdout7_disjoint_articles.csv", "holdout8_stratified_articles.csv"),
        ("홀드아웃7", "홀드아웃8"),
        ("holdout7", "holdout8"),
        ("disjoint 50", "stratified 48"),
        ("disjoint50_v4", "stratified48_v5"),
        ("holdout8_colab_input_bundle.zip", "holdout8_v5_colab_input_bundle.zip"),
        ("holdout8_gpu_results.zip", "holdout8_v5_gpu_results.zip"),
        ("kosis_meta_chroma_holdout7", "kosis_meta_chroma_holdout8"),
        ("assert len(articles) == 50", "assert len(articles) == 48"),
        ("assert len({r['URL'] for r in articles}) == 50", "assert len({r['URL'] for r in articles}) == 48"),
        ("assert len({r['article_id'] for r in sentences}) == 50", "assert len({r['article_id'] for r in sentences}) == 48"),
        ("원본 기사 50개", "원본 기사 48개"),
        ("# 12. v4 blind", "# 12. v5 blind"),
        ("첫 50건 회귀", "층화 48건 회귀"),
        ("mcp_gold_200_coordinate_ab_gpu_results_v4", "mcp_gold_200_coordinate_ab_gpu_results_v5"),
    )
    for cell in notebook["cells"]:
        source = "".join(cell.get("source", []))
        for old, new in replacements:
            source = source.replace(old, new)
        source = source.replace(
            "sys.executable, 'extract_hcx.py'",
            "sys.executable, '-u', 'extract_hcx.py'",
        )
        source = source.replace(
            "shutil.make_archive('/content/holdout8_v4_gpu_results'",
            "shutil.make_archive('/content/holdout8_v5_gpu_results'",
        )
        source = source.replace(
            "# 16. 요약·결과 ZIP 다운로드 (대용량 인덱스와 API 키 제외)\n"
            "from collections import Counter\n",
            "# 16. 요약·결과 ZIP 다운로드 (대용량 인덱스와 API 키 제외)\n"
            "from collections import Counter\n"
            "# 중단·재개 뒤 메모리 변수가 없어도 체크포인트 CSV에서 복구한다.\n"
            "measurements = csv_rows(OUT / '05_hcx_measurements.csv')\n",
        )
        source = source.replace(
            """def run(args):
    cmd = [str(x) for x in args]
    print('\\n$', ' '.join(cmd[:3]), '...')
    return subprocess.run(cmd, cwd=ROOT, env=os.environ.copy(), check=True)
""",
            """def run(args):
    cmd = [str(x) for x in args]
    print('\\n$', ' '.join(cmd[:3]), '...', flush=True)
    process = subprocess.Popen(
        cmd, cwd=ROOT, env=os.environ.copy(), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end='', flush=True)
    returncode = process.wait()
    if returncode:
        raise subprocess.CalledProcessError(returncode, cmd)
    return subprocess.CompletedProcess(cmd, returncode)
""",
        )
        cell["source"] = source.splitlines(keepends=True)
    NOTEBOOK.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def write_prereg() -> None:
    source_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8-sig"))
    PREREG.write_text(
        f"""# 홀드아웃8 v5 사전등록 — 구조화 OBJ 층화 48건

- 잠금 시각: `{source_manifest['created_at']}`
- 기사 수: `48`
- 층별 수: 국가 12 / 연령 12 / 성별 12 / 품목 12
- 기존 골드·홀드아웃 URL 중복: `0`
- 기사 입력 SHA-256: `{source_manifest['articles_sha256']}`
- 사람이 기사 내용을 읽고 선별: `false`

## 고정 규칙

1. 대상어·통계 지표·숫자가 같은 문장에 있는 기사만 후보로 삼는다.
2. 공식기관·공식통계 문맥에 가점을 주되 결과 정답은 선택에 사용하지 않는다.
3. 회사채·은행채·한전채·통안채·기업어음과 개별 회사 실적 문장은 KOSIS-ready에서 제외한다.
4. 표 Top-5와 Top-10은 동일한 HCX measurement와 동일한 인덱스에서 비교한다.
5. GPU 검색 완료 후 KOSIS MCP 검색→표 검증→실제 수치 조회가 성공한 행만 자동 골드로 확정한다.
6. MCP 자동 골드가 없는 행은 정확도 분모에서 제외하고 별도 미확정 목록에 남긴다.
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
        "purpose": "holdout8 v5 stratified Top-5/Top-10 MCP-auto-gold input",
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
    print(f"bundle_sha256={manifest['bundle_sha256']}")


if __name__ == "__main__":
    main()
