#!/usr/bin/env python3
"""Build the gold-blind locked300 v10 SQLite Colab notebook and input bundle."""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FREEZE_ID = "locked300-v10-sqlite-20260811"
OUTPUT_DIR = ROOT / "outputs/locked_holdout_300_v10_sqlite"
FREEZE = ROOT / "data/locked_holdout_300_v10_sqlite_freeze_manifest.json"
NOTEBOOK = ROOT / "notebooks/locked_holdout_300_v10_sqlite_gpu_colab.ipynb"
BUNDLE = OUTPUT_DIR / "locked_holdout_300_v10_sqlite_colab_input_bundle.zip"
PREREG = ROOT / "docs/locked_holdout_300_v10_sqlite_prereg_20260811.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    except Exception:
        return ""


def md(source: str) -> dict[str, object]:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def code(source: str) -> dict[str, object]:
    return {
        "cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def bundle_source_files() -> dict[str, Path]:
    files = {path.name: path for path in ROOT.glob("*.py")}
    for relative in (
        "requirements.txt",
        "requirements-ml.txt",
        "data/locked_holdout_300_articles.csv",
        "data/locked_holdout_300_assignments.csv",
        "data/locked_holdout_300_manifest.json",
        "data/reference/kosis_table_summary.csv",
        "docs/locked_holdout_300_v10_sqlite_prereg_20260811.md",
        "docs/kosis_vector_sqlite_exact_architecture.md",
    ):
        files[relative] = ROOT / relative
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"bundle inputs missing: {missing}")
    return files


def build_freeze(files: dict[str, Path]) -> dict[str, object]:
    lock = json.loads((ROOT / "data/locked_holdout_300_manifest.json").read_text(encoding="utf-8"))
    payload = {
        "schema_version": 1,
        "freeze_id": FREEZE_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git_value("rev-parse", "HEAD"),
        "git_branch": git_value("branch", "--show-current"),
        "working_tree_clean": not bool(git_value("status", "--porcelain")),
        "gold_accessed": False,
        "article_count": 300,
        "article_sha256": lock["articles_sha256"],
        "holdout_lock_status": lock["lock_status"],
        "holdout_label_status": lock["label_status"],
        "pipeline": {
            "hcx_model": "HCX-007",
            "table_retrieval": "lexical+bge-m3+reranker",
            "embedding_model": "BAAI/bge-m3",
            "embedding_dimension": 1024,
            "reranker_model": "BAAI/bge-reranker-v2-m3",
            "table_top_k": 10,
            "metadata_top_k": 10,
            "coordinate_backend": "sqlite",
            "sqlite_schema": "kosis-sqlite-metadata-v1",
            "item_top_k": 5,
            "coordinate_chroma_used": False,
            "api_validation": True,
            "value_verification": True,
        },
        "files": {name: sha256(path) for name, path in sorted(files.items())},
    }
    FREEZE.parent.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def build_notebook() -> None:
    cells = [
        md("""# 잠금 홀드아웃 300 v10-sqlite

이 노트북은 좌표 Chroma를 사용하지 않고 `표 BGE/Reranker → SQLite ITEM·OBJ exact resolver → KOSIS API` 경로로 새 기사 300건의 예측을 먼저 고정합니다.

- 정답 골드는 번들에 포함되지 않습니다.
- 중간 출력과 SQLite DB는 Google Drive에 저장됩니다.
- Colab Secrets에 `CLOVA_API_KEY`, `KOSIS_API_KEY`를 등록하세요.
- 이전 `locked_holdout_300_v9` 노트북은 실행하지 않습니다.
"""),
        code(r"""# 1. GPU 확인
import subprocess
gpu = subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True, check=True)
print(gpu.stdout.strip())
assert 'GPU' in gpu.stdout, '런타임 유형을 GPU로 변경하세요.'
"""),
        code(r"""# 2. 입력 번들 업로드, 안전한 해제, Google Drive 체크포인트
from google.colab import files, drive
from pathlib import Path
import csv, hashlib, io, json, os, shutil, subprocess, sys, zipfile

os.chdir('/content')
uploaded = files.upload()
bundles = [name for name in uploaded if name.endswith('.zip')]
assert len(bundles) == 1, 'locked_holdout_300_v10_sqlite_colab_input_bundle.zip 하나만 업로드하세요.'
ROOT = Path('/content/locked300_v10_sqlite')
if ROOT.exists():
    shutil.rmtree(ROOT)
ROOT.mkdir(parents=True)
with zipfile.ZipFile(io.BytesIO(uploaded[bundles[0]])) as archive:
    for info in archive.infolist():
        parts = [part for part in info.filename.replace('\\', '/').split('/') if part not in {'', '.'}]
        assert '..' not in parts, f'안전하지 않은 ZIP 경로: {info.filename}'
        target = ROOT.joinpath(*parts)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
assert (ROOT / 'data/locked_holdout_300_articles.csv').is_file()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

drive.mount('/content/drive')
DRIVE = Path('/content/drive/MyDrive/kosis_locked300_v10_sqlite_run')
RUN = DRIVE / 'outputs'
MAP = RUN / '07_mapping_sqlite'
SEM = DRIVE / 'indexes/kosis_bge_m3'
SQLDB = DRIVE / 'indexes/kosis_metadata.sqlite'
RUN.mkdir(parents=True, exist_ok=True)
MAP.mkdir(parents=True, exist_ok=True)

def run(args):
    cmd = [str(value) for value in args]
    print('\n$', ' '.join(cmd[:4]), '...', flush=True)
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

def csv_rows(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return []
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))

def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

print('ROOT =', ROOT)
print('RUN =', RUN)
print('SQLDB =', SQLDB)
"""),
        code(r"""# 3. 번들과 v10 freeze 무결성 확인
bundle_manifest = json.loads((ROOT / 'bundle_manifest.json').read_text(encoding='utf-8'))
for rel, expected in bundle_manifest['files'].items():
    assert file_hash(ROOT / rel) == expected, f'번들 해시 불일치: {rel}'
freeze = json.loads((ROOT / 'data/locked_holdout_300_v10_sqlite_freeze_manifest.json').read_text(encoding='utf-8'))
assert freeze['freeze_id'] == 'locked300-v10-sqlite-20260811'
assert freeze['gold_accessed'] is False
assert freeze['article_count'] == 300
assert freeze['pipeline']['coordinate_backend'] == 'sqlite'
assert freeze['pipeline']['coordinate_chroma_used'] is False
print('freeze verified:', freeze['freeze_id'], '| files:', len(freeze['files']))
"""),
        code(r"""# 4. 의존성 설치
%pip install -q -r requirements.txt -r requirements-ml.txt
import pandas as pd, sentence_transformers, torch
assert torch.cuda.is_available(), 'CUDA를 사용할 수 없습니다.'
print('torch', torch.__version__, '| GPU', torch.cuda.get_device_name(0))
"""),
        code(r"""# 5. 비밀키 설정
from getpass import getpass
try:
    from google.colab import userdata
except Exception:
    userdata = None

def secret(name):
    value = ''
    if userdata is not None:
        try:
            value = userdata.get(name) or ''
        except Exception:
            pass
    return value or getpass(f'{name}: ')

os.environ['CLOVA_API_KEY'] = secret('CLOVA_API_KEY')
os.environ['KOSIS_API_KEY'] = secret('KOSIS_API_KEY')
assert os.environ['CLOVA_API_KEY'] and os.environ['KOSIS_API_KEY']
print('API 키가 메모리에만 설정되었습니다.')
"""),
        code(r"""# 6. KOSIS 표 BGE-M3 인덱스 생성 또는 동일 해시 캐시 재사용
TABLES = ROOT / 'data/reference/kosis_table_summary.csv'
sem_manifest = SEM / 'manifest.json'
reuse_sem = False
if sem_manifest.is_file():
    info = json.loads(sem_manifest.read_text(encoding='utf-8'))
    reuse_sem = (
        info.get('source_sha256') == file_hash(TABLES)
        and info.get('embedding_model') == 'BAAI/bge-m3'
        and int(info.get('dimension', 0)) == 1024
    )
if not reuse_sem:
    if SEM.exists():
        shutil.rmtree(SEM)
    run([sys.executable, 'kosis_build_embedding_index.py', '--table-index', TABLES,
         '--out-dir', SEM, '--batch-size', '16', '--device', 'cuda'])
assert sem_manifest.is_file()
print('semantic index:', 'reused' if reuse_sem else 'built', SEM)
"""),
        code(r"""# 7. 기사 → claim context 생성, HCX 출력 기준 재개
run([sys.executable, 'run_contextual_news_kosis_pipeline.py',
     '--articles', ROOT / 'data/locked_holdout_300_articles.csv',
     '--table-index', TABLES, '--semantic-index', SEM, '--out-dir', RUN,
     '--model', 'HCX-007', '--device', 'cuda', '--sleep', '0.5', '--stop-after', 'contexts'])
articles = csv_rows(ROOT / 'data/locked_holdout_300_articles.csv')
contexts = csv_rows(RUN / '03_claim_contexts.csv')
assert len(articles) == 300
print('articles =', len(articles), '| claim contexts =', len(contexts))
"""),
        code(r"""# 8. 조기 표 검색과 HCX measurement 추출
run([sys.executable, 'kosis_early_retrieve.py', '--input', RUN / '03_claim_contexts.csv',
     '--output-candidates', RUN / '04_early_bge_candidates_top20.csv',
     '--output-context', RUN / '04_early_bge_context_top5.csv',
     '--semantic-index', SEM, '--semantic-top-k', '20', '--rerank-top-k', '20',
     '--context-top-k', '5', '--device', 'cuda'])
run([sys.executable, '-u', 'extract_hcx.py', '--input', RUN / '03_claim_contexts.csv',
     '--retrieval-context', RUN / '04_early_bge_context_top5.csv',
     '--output', RUN / '05_hcx_measurements.csv', '--model', 'HCX-007', '--sleep', '0.5'])
measurements = csv_rows(RUN / '05_hcx_measurements.csv')
assert measurements, 'measurement가 생성되지 않았습니다.'
print('measurement rows =', len(measurements))
"""),
        code(r"""# 9. 표 BGE/Reranker → SQLite exact resolver → KOSIS API → 값 검증
mapping_cmd = [
    sys.executable, 'run_kosis_measurement_pipeline.py',
    '--input', RUN / '05_hcx_measurements.csv',
    '--table-index', TABLES,
    '--semantic-index', SEM,
    '--out-dir', MAP,
    '--retrieval-mode', 'hybrid',
    '--semantic-top-k', '50',
    '--rerank-top-k', '60',
    '--lexical-reserve-k', '10',
    '--top-tables', '10',
    '--top-rank-for-meta', '10',
    '--item-top-k', '5',
    '--coordinate-backend', 'sqlite',
    '--metadata-db', SQLDB,
    '--device', 'cuda',
    '--verify',
]
table_candidates = MAP / '05_hcx_measurements_kosis_table_candidates.csv'
if table_candidates.is_file():
    mapping_cmd.append('--reuse-table-candidates')
run(mapping_cmd)

SQL_OUT = MAP / 'sqlite_exact'
SELECTED = SQL_OUT / '02_sqlite_selected_coordinates.csv'
VALIDATED = SQL_OUT / '03_sqlite_api_validated.csv'
VERIFIED = SQL_OUT / '04_sqlite_value_verified.csv'
sql_summary = json.loads((SQL_OUT / 'summary.json').read_text(encoding='utf-8'))
assert sql_summary['coordinate_chroma_used'] is False
print(json.dumps(sql_summary, ensure_ascii=False, indent=2))
"""),
        code(r"""# 10. 정답 비공개 예측 파일 고정
PRED = RUN / 'locked_holdout_300_predictions.csv'
ARTICLE_PRED = RUN / 'locked_holdout_300_article_predictions.csv'
PRED_MANIFEST = RUN / 'locked_holdout_300_prediction_manifest.json'
export_cmd = [
    sys.executable, 'export_locked_holdout_300_predictions.py',
    '--articles', ROOT / 'data/locked_holdout_300_articles.csv',
    '--measurements', RUN / '05_hcx_measurements.csv',
    '--mapped', VALIDATED,
    '--output', PRED,
    '--article-output', ARTICLE_PRED,
    '--manifest', PRED_MANIFEST,
]
if VERIFIED.is_file() and VERIFIED.stat().st_size:
    export_cmd.extend(['--verified', VERIFIED])
run(export_cmd)
prediction_manifest = json.loads(PRED_MANIFEST.read_text(encoding='utf-8'))
assert prediction_manifest['gold_accessed'] is False
assert prediction_manifest['article_count'] == 300
print(json.dumps(prediction_manifest, ensure_ascii=False, indent=2))
"""),
        code(r"""# 11. 결과 요약과 ZIP 다운로드, 인덱스·SQLite DB는 Drive에 유지
from collections import Counter
db_manifest = Path(str(SQLDB) + '.manifest.json')
summary = {
    'freeze_id': freeze['freeze_id'],
    'architecture': 'table-vector-search -> sqlite-exact-resolver -> kosis-api',
    'coordinate_chroma_used': False,
    'articles': len(articles),
    'claim_contexts': len(contexts),
    'measurements': len(measurements),
    'sqlite_summary': sql_summary,
    'prediction_sha256': prediction_manifest['predictions_sha256'],
    'article_prediction_sha256': prediction_manifest['article_predictions_sha256'],
    'gold_accessed': False,
    'semantic_manifest': json.loads(sem_manifest.read_text(encoding='utf-8')),
    'sqlite_manifest': json.loads(db_manifest.read_text(encoding='utf-8')) if db_manifest.is_file() else {},
}
(RUN / 'gpu_run_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
archive = shutil.make_archive('/content/locked_holdout_300_v10_sqlite_gpu_results', 'zip', RUN)
print(json.dumps(summary, ensure_ascii=False, indent=2))
print('다운로드:', archive)
files.download(archive)
"""),
        md("""## 완료

다운로드한 `locked_holdout_300_v10_sqlite_gpu_results.zip`을 Codex에 첨부하세요.

중단되면 같은 노트북과 번들을 다시 실행하면 Google Drive의 HCX 출력·표 후보·SQLite DB를 기준으로 재개합니다.
"""),
    ]
    notebook = {
        "cells": cells,
        "metadata": {
            "accelerator": "GPU",
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    NOTEBOOK.parent.mkdir(parents=True, exist_ok=True)
    NOTEBOOK.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def build_bundle(files: dict[str, Path]) -> dict[str, object]:
    archive_files = dict(files)
    archive_files["data/locked_holdout_300_v10_sqlite_freeze_manifest.json"] = FREEZE
    manifest = {
        "schema_version": 1,
        "freeze_id": FREEZE_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "gold-blind locked300 v10 SQLite predictions",
        "secrets_included": False,
        "gold_included": False,
        "coordinate_chroma_included": False,
        "article_count": 300,
        "files": {name: sha256(path) for name, path in sorted(archive_files.items())},
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BUNDLE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(archive_files.items()):
            archive.write(path, name)
        archive.writestr("bundle_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    manifest["bundle_sha256"] = sha256(BUNDLE)
    manifest["bundle_size_bytes"] = BUNDLE.stat().st_size
    return manifest


def main() -> None:
    files = bundle_source_files()
    freeze = build_freeze(files)
    build_notebook()
    bundle = build_bundle(files)
    print(json.dumps({
        "freeze": str(FREEZE),
        "notebook": str(NOTEBOOK),
        "bundle": str(BUNDLE),
        "freeze_id": freeze["freeze_id"],
        "bundle_manifest": bundle,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
