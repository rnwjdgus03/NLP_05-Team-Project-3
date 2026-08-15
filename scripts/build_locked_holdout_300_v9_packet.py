#!/usr/bin/env python3
"""Freeze v9 and build a resumable Colab packet for locked holdout 300."""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FREEZE_ID = "locked300-v9-20260810"
OUTPUT_DIR = ROOT / "outputs/locked_holdout_300_v9"
FREEZE = ROOT / "data/locked_holdout_300_v9_freeze_manifest.json"
NOTEBOOK = ROOT / "notebooks/locked_holdout_300_v9_gpu_colab.ipynb"
BUNDLE = OUTPUT_DIR / "locked_holdout_300_v9_colab_input_bundle.zip"
PREREG = ROOT / "docs/locked_holdout_300_v9_prereg_20260810.md"


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


def frozen_files() -> dict[str, Path]:
    files = {path.name: path for path in ROOT.glob("*.py")}
    for relative in (
        "requirements.txt",
        "requirements-ml.txt",
        "data/locked_holdout_300_articles.csv",
        "data/locked_holdout_300_assignments.csv",
        "data/locked_holdout_300_manifest.json",
        "data/reference/kosis_table_summary.csv",
        "docs/locked_holdout_300_v9_prereg_20260810.md",
    ):
        files[relative] = ROOT / relative
    return files


def build_freeze_manifest(files: dict[str, Path]) -> dict[str, object]:
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"freeze inputs missing: {missing}")
    holdout = json.loads((ROOT / "data/locked_holdout_300_manifest.json").read_text(encoding="utf-8"))
    payload = {
        "schema_version": 1,
        "freeze_id": FREEZE_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git_value("rev-parse", "HEAD"),
        "git_branch": git_value("branch", "--show-current"),
        "working_tree_clean": not bool(git_value("status", "--porcelain")),
        "gold_accessed": False,
        "holdout_lock_status": holdout["lock_status"],
        "holdout_label_status": holdout["label_status"],
        "article_count": holdout["row_count"],
        "article_sha256": holdout["articles_sha256"],
        "pipeline": {
            "hcx_model": "HCX-007",
            "embedding_model": "BAAI/bge-m3",
            "embedding_dimension": 1024,
            "reranker_model": "BAAI/bge-reranker-v2-m3",
            "table_top_k_primary": 5,
            "table_top_k_fallback": 10,
            "semantic_top_k": 50,
            "lexical_top_k": 50,
            "rerank_top_k": 60,
            "final_top_k": 30,
            "axis_value_limit": 300,
            "max_coordinates_per_table": 4000,
            "strict_seeded_coordinate": True,
            "obj_relaxation_can_ready": False,
            "top10_fallback_can_auto_ready": False,
        },
        "files": {name: sha256(path) for name, path in sorted(files.items())},
    }
    FREEZE.parent.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def build_notebook() -> None:
    cells = [
        md("""# 잠금 홀드아웃 300 v9 예측 고정

이 노트북은 정답 골드를 포함하지 않으며 새 기사 300건의 예측을 먼저 고정합니다.

- Colab GPU 런타임을 사용합니다.
- 단계별 출력은 Google Drive의 `kosis_locked300_v9_run`에 저장되어 중단 후 재개됩니다.
- `CLOVA_API_KEY`, `KOSIS_API_KEY`를 Colab Secrets에 등록합니다.
- 기존 Chroma ZIP은 현재 meta-index 해시가 정확히 같을 때만 재사용합니다.
"""),
        code("""# 1. GPU 확인
import subprocess
gpu = subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True, check=True)
print(gpu.stdout.strip())
assert 'GPU' in gpu.stdout, '런타임 유형을 GPU로 변경하세요.'
"""),
        code("""# 2. 입력 번들 업로드와 안전한 해제
from google.colab import files, drive
from pathlib import Path
import csv, hashlib, io, json, os, shutil, subprocess, sys, zipfile

os.chdir('/content')
uploaded = files.upload()
bundles = [name for name in uploaded if name.endswith('.zip')]
assert len(bundles) == 1, 'locked_holdout_300_v9_colab_input_bundle.zip 하나만 업로드하세요.'
ROOT = Path('/content/locked300_v9')
if ROOT.exists():
    shutil.rmtree(ROOT)
ROOT.mkdir(parents=True)
with zipfile.ZipFile(io.BytesIO(uploaded[bundles[0]])) as archive:
    for info in archive.infolist():
        parts = [part for part in info.filename.replace('\\\\', '/').split('/') if part not in {'', '.'}]
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
DRIVE = Path('/content/drive/MyDrive/kosis_locked300_v9_run')
RUN = DRIVE / 'outputs'
MAP = RUN / '07_mapping_v9'
SEM = DRIVE / 'indexes/kosis_bge_m3'
RUN.mkdir(parents=True, exist_ok=True)
MAP.mkdir(parents=True, exist_ok=True)

def run(args):
    cmd = [str(value) for value in args]
    print('\\n$', ' '.join(cmd[:4]), '...', flush=True)
    process = subprocess.Popen(cmd, cwd=ROOT, env=os.environ.copy(), stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end='', flush=True)
    returncode = process.wait()
    if returncode:
        raise subprocess.CalledProcessError(returncode, cmd)
    return subprocess.CompletedProcess(cmd, returncode)

def csv_rows(path):
    if not Path(path).is_file() or Path(path).stat().st_size == 0:
        return []
    with open(path, encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))

def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

print('ROOT =', ROOT)
print('RUN =', RUN)
"""),
        code("""# 3. 번들·동결 manifest 무결성 확인
bundle_manifest = json.loads((ROOT / 'bundle_manifest.json').read_text(encoding='utf-8'))
for rel, expected in bundle_manifest['files'].items():
    assert file_hash(ROOT / rel) == expected, f'번들 해시 불일치: {rel}'
freeze = json.loads((ROOT / 'data/locked_holdout_300_v9_freeze_manifest.json').read_text(encoding='utf-8'))
assert freeze['freeze_id'] == 'locked300-v9-20260810'
assert freeze['gold_accessed'] is False
assert freeze['article_count'] == 300
assert freeze['holdout_lock_status'] == 'LOCKED_DO_NOT_TUNE'
print('freeze verified:', freeze['freeze_id'], '| files:', len(freeze['files']))
"""),
        code("""# 4. 의존성 설치
%pip install -q -r requirements.txt -r requirements-ml.txt
import chromadb, pandas as pd, sentence_transformers, torch
assert torch.cuda.is_available(), 'CUDA를 사용할 수 없습니다.'
print('torch', torch.__version__, '| GPU', torch.cuda.get_device_name(0))
"""),
        code("""# 5. 비밀키 설정
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
        code("""# 6. KOSIS 표 BGE-M3 인덱스 생성 또는 해시 일치 캐시 재사용
TABLES = ROOT / 'data/reference/kosis_table_summary.csv'
sem_manifest = SEM / 'manifest.json'
reuse_sem = False
if sem_manifest.is_file():
    meta = json.loads(sem_manifest.read_text(encoding='utf-8'))
    reuse_sem = meta.get('source_sha256') == file_hash(TABLES) and meta.get('embedding_model') == 'BAAI/bge-m3'
if not reuse_sem:
    if SEM.exists():
        shutil.rmtree(SEM)
    run([sys.executable, 'kosis_build_embedding_index.py', '--table-index', TABLES,
         '--out-dir', SEM, '--batch-size', '16', '--device', 'cuda'])
assert sem_manifest.is_file()
print('semantic index:', 'reused' if reuse_sem else 'built', SEM)
"""),
        code("""# 7. 기사 → claim context 생성, Google Drive 체크포인트 재개
run([sys.executable, 'run_contextual_news_kosis_pipeline.py',
     '--articles', ROOT / 'data/locked_holdout_300_articles.csv',
     '--table-index', TABLES, '--semantic-index', SEM, '--out-dir', RUN,
     '--model', 'HCX-007', '--device', 'cuda', '--sleep', '0.5', '--stop-after', 'contexts'])
articles = csv_rows(ROOT / 'data/locked_holdout_300_articles.csv')
contexts = csv_rows(RUN / '03_claim_contexts.csv')
assert len(articles) == 300
print('articles =', len(articles), '| claim contexts =', len(contexts))
"""),
        code("""# 8. 조기 표 검색과 HCX measurement 추출, 출력 파일 기준 재개
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
        code("""# 9. 상류 표 검색과 KOSIS meta-index 생성
run([sys.executable, 'prepare_kosis_mapping_input.py', '--input', RUN / '05_hcx_measurements.csv',
     '--output', RUN / '06_mapping_ready.csv', '--enrich-output', RUN / '06_mapping_enrich.csv',
     '--rejected-output', RUN / '06_mapping_reject.csv', '--all-output', RUN / '06_in_ready_all.csv'])
run([sys.executable, 'run_kosis_measurement_pipeline.py', '--input', RUN / '05_hcx_measurements.csv',
     '--table-index', TABLES, '--semantic-index', SEM, '--out-dir', MAP,
     '--retrieval-mode', 'hybrid', '--semantic-top-k', '50', '--rerank-top-k', '60',
     '--top-tables', '20', '--lexical-reserve-k', '10', '--top-rank-for-meta', '20', '--device', 'cuda'])
READY = MAP / '05_hcx_measurements_kosis_ready.csv'
META = MAP / '05_hcx_measurements_kosis_meta_index.csv'
TABLE_CAND = MAP / '05_hcx_measurements_kosis_table_candidates.csv'
EVAL = MAP / 'evaluation_set.csv'
run([sys.executable, 'lock_evaluation_set.py', '--ready', READY, '--output', EVAL,
     '--excluded-output', MAP / 'evaluation_set_excluded.csv',
     '--manifest', MAP / 'evaluation_set_manifest.json'])
print('evaluation rows =', len(csv_rows(EVAL)))
"""),
        code("""# 10. 현재 meta 해시에 맞는 Chroma만 재사용하고 아니면 새로 생성
meta_hash = file_hash(META)
CHR = DRIVE / 'indexes' / f'kosis_meta_chroma_{meta_hash[:12]}'
chroma_manifest = CHR / 'chroma_manifest.json'
reuse_chroma = False
if chroma_manifest.is_file():
    info = json.loads(chroma_manifest.read_text(encoding='utf-8'))
    reuse_chroma = (info.get('source_meta_sha256') == meta_hash and
                    info.get('collection') == 'kosis_meta_coordinates' and
                    info.get('embedding_model') == 'BAAI/bge-m3')

# 사용자가 Drive에 올린 기존 ZIP은 source meta 해시가 같을 때만 해제합니다.
legacy_zip = Path('/content/drive/MyDrive/kosis_meta_chroma_holdout8_v8.zip')
if not reuse_chroma and legacy_zip.is_file():
    with zipfile.ZipFile(legacy_zip) as archive:
        members = [name for name in archive.namelist() if name.endswith('chroma_manifest.json')]
        if members:
            legacy_info = json.loads(archive.read(members[0]).decode('utf-8'))
            if legacy_info.get('source_meta_sha256') == meta_hash:
                archive.extractall(CHR.parent)
                reuse_chroma = chroma_manifest.is_file()

if not reuse_chroma:
    if CHR.exists():
        shutil.rmtree(CHR)
    run([sys.executable, 'kosis_build_chroma_meta_index.py', '--meta-index', META,
         '--persist-dir', CHR, '--collection', 'kosis_meta_coordinates',
         '--embedding-model', 'BAAI/bge-m3', '--axis-value-limit', '300',
         '--prd-se-source', TABLE_CAND, '--batch-size', '64', '--device', 'cuda', '--reset'])
assert chroma_manifest.is_file()
print('Chroma:', 'reused' if reuse_chroma else 'built', CHR)
"""),
        code("""# 11. v9 Top-5/Top-10 검색과 ITEM·OBJ 2단계 선택
EVAL_V9 = MAP / 'evaluation_set_v9_enriched.csv'
run([sys.executable, 'enrich_mcp_gold_200_inputs.py', '--input', EVAL, '--output', EVAL_V9,
     '--stats', MAP / 'v9_enrichment_stats.json'])
CAND5 = MAP / 'chroma_candidates_top5.csv'
CAND10 = MAP / 'chroma_candidates_top10.csv'
for table_k, output, stats in [('5', CAND5, MAP / 'chroma_stats_top5.csv'),
                               ('10', CAND10, MAP / 'chroma_stats_top10.csv')]:
    run([sys.executable, 'kosis_chroma_hybrid_search.py', '--claims', EVAL_V9,
         '--table-candidates', TABLE_CAND, '--persist-dir', CHR,
         '--collection', 'kosis_meta_coordinates', '--output', output, '--stats-output', stats,
         '--table-top-k', table_k, '--dense-top-k', '50', '--lexical-top-k', '50',
         '--rerank-top-k', '60', '--final-top-k', '30', '--min-candidates-per-table', '3',
         '--reranker-model', 'BAAI/bge-reranker-v2-m3', '--device', 'cuda'])
SELECT5 = MAP / 'two_stage_selected_top5.csv'
SELECT10 = MAP / 'two_stage_selected_top10.csv'
for candidates, selected in [(CAND5, SELECT5), (CAND10, SELECT10)]:
    run([sys.executable, 'select_mcp_gold_200_two_stage_coordinates.py', '--claims', EVAL_V9,
         '--candidates', candidates, '--output', selected, '--item-top-k', '10'])
print('selected rows =', len(csv_rows(SELECT5)), len(csv_rows(SELECT10)))
"""),
        code("""# 12. KOSIS API 좌표 검증, 제한적 Top-10 폴백, READY 값 검증
VALID5 = MAP / 'chroma_validated_top5.csv'
FALLBACK_IN = MAP / 'top10_fallback_input.csv'
FALLBACK_VALID = MAP / 'top10_fallback_validated.csv'
FINAL = MAP / 'chroma_validated_bounded_fallback.csv'

def validate_selected(selected, output):
    run([sys.executable, 'kosis_validate_mapping_candidates.py', '--input', selected,
         '--meta-index', META, '--output', output, '--evaluate-all-ranks',
         '--strict-seeded-coordinate', '--item-top-k', '1', '--obj-top-k', '1',
         '--max-combinations', '1', '--allow-provisional', '--relax-empty-obj',
         '--max-relaxed-requests', '4', '--max-relaxed-obj-drops', '2'])

validate_selected(SELECT5, VALID5)
run([sys.executable, 'kosis_topk_fallback.py', 'prepare', '--primary-validated', VALID5,
     '--fallback-candidates', SELECT10, '--output', FALLBACK_IN])
if csv_rows(FALLBACK_IN):
    validate_selected(FALLBACK_IN, FALLBACK_VALID)
else:
    FALLBACK_VALID.write_text('', encoding='utf-8')
run([sys.executable, 'kosis_topk_fallback.py', 'merge', '--primary-validated', VALID5,
     '--fallback-validated', FALLBACK_VALID, '--output', FINAL])
final_rows = csv_rows(FINAL)
assert all(row.get('mapping_status') != 'READY' for row in final_rows if row.get('obj_relaxation_used') == 'Y')

ready_df = pd.DataFrame([row for row in final_rows if row.get('mapping_status') == 'READY'])
VERIFY_IN = MAP / 'verify_input.csv'
VERIFIED = MAP / 'verified.csv'
if len(ready_df):
    ready_df.to_csv(VERIFY_IN, index=False, encoding='utf-8-sig')
    run([sys.executable, 'kosis_verify_claim_values.py', '--input', VERIFY_IN,
         '--output', VERIFIED, '--delay', '0.12'])
else:
    VERIFIED.write_text('', encoding='utf-8')
print('final rows =', len(final_rows), '| READY =', len(ready_df))
"""),
        code("""# 13. 정답 비공개 예측 파일 고정
PRED = RUN / 'locked_holdout_300_predictions.csv'
ARTICLE_PRED = RUN / 'locked_holdout_300_article_predictions.csv'
PRED_MANIFEST = RUN / 'locked_holdout_300_prediction_manifest.json'
run([sys.executable, 'export_locked_holdout_300_predictions.py',
     '--articles', ROOT / 'data/locked_holdout_300_articles.csv',
     '--measurements', RUN / '05_hcx_measurements.csv', '--mapped', FINAL,
     '--verified', VERIFIED, '--output', PRED, '--article-output', ARTICLE_PRED,
     '--manifest', PRED_MANIFEST])
prediction_manifest = json.loads(PRED_MANIFEST.read_text(encoding='utf-8'))
assert prediction_manifest['gold_accessed'] is False
assert prediction_manifest['article_count'] == 300
print(json.dumps(prediction_manifest, ensure_ascii=False, indent=2))
"""),
        code("""# 14. 결과 ZIP 생성 및 다운로드, 대용량 인덱스는 Drive에 유지
from collections import Counter
summary = {
    'freeze_id': freeze['freeze_id'],
    'articles': len(articles),
    'claim_contexts': len(contexts),
    'measurements': len(measurements),
    'evaluation_measurements': len(csv_rows(EVAL)),
    'mapping_status_rows': dict(Counter(row.get('mapping_status', '') for row in final_rows)),
    'prediction_sha256': prediction_manifest['predictions_sha256'],
    'article_prediction_sha256': prediction_manifest['article_predictions_sha256'],
    'gold_accessed': False,
    'semantic_manifest': json.loads(sem_manifest.read_text(encoding='utf-8')),
    'chroma_manifest': json.loads(chroma_manifest.read_text(encoding='utf-8')),
}
(RUN / 'gpu_run_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
archive = shutil.make_archive('/content/locked_holdout_300_v9_gpu_results', 'zip', RUN)
print(json.dumps(summary, ensure_ascii=False, indent=2))
print('다운로드:', archive)
files.download(archive)
"""),
        md("""## 완료 조건

다운로드한 `locked_holdout_300_v9_gpu_results.zip`을 Codex에 첨부하세요.

중간에 중단되면 같은 번들을 다시 올리고 셀을 순서대로 실행하면 Google Drive 출력 파일을 기준으로 재개됩니다.
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
    bundle_files = dict(files)
    bundle_files["data/locked_holdout_300_v9_freeze_manifest.json"] = FREEZE
    missing = [str(path) for path in bundle_files.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"bundle files missing: {missing}")
    manifest = {
        "schema_version": 1,
        "freeze_id": FREEZE_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "gold-blind locked holdout 300 v9 predictions",
        "secrets_included": False,
        "gold_included": False,
        "article_count": 300,
        "files": {name: sha256(path) for name, path in sorted(bundle_files.items())},
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BUNDLE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(bundle_files.items()):
            archive.write(path, name)
        archive.writestr("bundle_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    manifest["bundle_sha256"] = sha256(BUNDLE)
    manifest["bundle_size_bytes"] = BUNDLE.stat().st_size
    return manifest


def main() -> None:
    files = frozen_files()
    freeze = build_freeze_manifest(files)
    build_notebook()
    bundle = build_bundle(files)
    print(f"freeze={FREEZE}")
    print(f"notebook={NOTEBOOK}")
    print(f"bundle={BUNDLE}")
    print(json.dumps({"freeze": freeze, "bundle": bundle}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
