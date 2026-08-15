#!/usr/bin/env python3
"""Build the MCP-gold v11 SQLite-metadata reranker Colab packet."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/mcp_gold_200_v11_metadata_reranker"
NOTEBOOK = ROOT / "notebooks/mcp_gold_200_v11_metadata_reranker_gpu_colab.ipynb"
BUNDLE = OUT / "mcp_gold_200_v11_metadata_reranker_colab_input_bundle.zip"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md(source: str) -> dict[str, object]:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def code(source: str) -> dict[str, object]:
    return {
        "cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def source_files() -> dict[str, Path]:
    files = {path.name: path for path in ROOT.glob("*.py")}
    files.update({
        "requirements-ml.txt": ROOT / "requirements-ml.txt",
        "data/dev/enriched_inputs.csv": ROOT / "outputs/mcp_gold_200_coordinate_ab_gpu_results_v6/enriched_inputs.csv",
        "data/dev/table_candidates.csv": ROOT / "outputs/mcp_gold_200_coordinate_ab_gpu_results_v6/table_candidates.csv",
        "data/dev/trusted_pass_119.csv": ROOT / "outputs/regression/v11_dev_gold_audit/trusted_pass_119.csv",
        "data/dev/gold_audit_summary.json": ROOT / "outputs/regression/v11_dev_gold_audit/summary.json",
        "data/gold/mcp_full_gold_200.csv": ROOT / "data/gold/mcp_full_gold_200.csv",
        "data/index/kosis_metadata.sqlite": ROOT / "outputs/regression/v11_dev_sqlite/kosis_metadata.sqlite",
        "data/index/kosis_metadata.sqlite.manifest.json": ROOT / "outputs/regression/v11_dev_sqlite/kosis_metadata.sqlite.manifest.json",
    })
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing packet inputs: {missing}")
    return files


def build_notebook() -> None:
    cells = [
        md("""# MCP Gold 200 v11 — SQLite metadata-aware reranker

한 번의 BGE Reranker GPU 추론 결과를 재사용해 다음을 자동 비교합니다.

- 메타데이터 융합 가중치: `0.00, 0.20, 0.35, 0.50, 0.65, 0.80, 1.00`
- SQLite 좌표 선택: `joint, table_top3, table_locked`
- 개발 선택 기준: 좌표 감사를 통과한 119건의 Full Mapping → ITEM·OBJ → 표 정확도
- 전체 200건 평가는 오염 진단용으로만 병기합니다.

이 노트북은 KOSIS API나 HCX API를 호출하지 않습니다.
"""),
        code(r"""# 1. GPU 확인
import subprocess
gpu = subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True, check=True)
print(gpu.stdout.strip())
assert 'GPU' in gpu.stdout, '런타임 유형을 GPU로 변경하세요.'
"""),
        code(r"""# 2. 입력 번들 업로드·안전한 해제·Drive 체크포인트
from google.colab import files, drive
from pathlib import Path
import csv, hashlib, io, json, os, shutil, subprocess, sys, zipfile

os.chdir('/content')
uploaded = files.upload()
bundles = [name for name in uploaded if name.endswith('.zip')]
assert len(bundles) == 1, 'mcp_gold_200_v11_metadata_reranker_colab_input_bundle.zip 하나만 업로드하세요.'
ROOT = Path('/content/mcp_gold_v11_metadata')
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

assert (ROOT / 'data/dev/enriched_inputs.csv').is_file(), '번들 해제에 실패했습니다.'
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
drive.mount('/content/drive')
DRIVE = Path('/content/drive/MyDrive/kosis_mcp_gold_v11_metadata_reranker')
RUN = DRIVE / 'run'
RUN.mkdir(parents=True, exist_ok=True)

def run(args):
    cmd = [str(value) for value in args]
    print('\n$', ' '.join(cmd[:5]), '...', flush=True)
    process = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end='', flush=True)
    code = process.wait()
    if code:
        raise subprocess.CalledProcessError(code, cmd)

def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

print('ROOT =', ROOT)
print('RUN =', RUN)
"""),
        code(r"""# 3. 번들 무결성 확인
manifest = read_json(ROOT / 'bundle_manifest.json')
for relative, expected in manifest['files'].items():
    actual = file_hash(ROOT / relative)
    assert actual == expected, f'해시 불일치: {relative}'
assert manifest['trusted_gold_rows'] == 119
assert manifest['full_gold_rows'] == 200
print('verified files =', len(manifest['files']))
print('bundle sha256 =', manifest['payload_sha256'])
"""),
        code(r"""# 4. 최소 의존성 설치
%pip install -q "transformers>=4.45,<6"
import torch, transformers
assert torch.cuda.is_available(), 'CUDA를 사용할 수 없습니다.'
print('torch', torch.__version__, '| transformers', transformers.__version__)
print('GPU', torch.cuda.get_device_name(0))
"""),
        code(r"""# 5. BGE 메타데이터 재순위 점수 1회 생성 또는 체크포인트 재사용
CLAIMS = ROOT / 'data/dev/enriched_inputs.csv'
TABLES = ROOT / 'data/dev/table_candidates.csv'
DB = ROOT / 'data/index/kosis_metadata.sqlite'
RAW = RUN / 'metadata_reranker_scored_top10.csv'
RAW_META = RUN / 'metadata_reranker_scored_top10.manifest.json'
expected = {
    'claims_sha256': file_hash(CLAIMS),
    'table_candidates_sha256': file_hash(TABLES),
    'sqlite_sha256': file_hash(DB),
    'model': 'BAAI/bge-reranker-v2-m3',
    'top_k': 10,
}
reuse = RAW.is_file() and RAW_META.is_file() and read_json(RAW_META) == expected
if not reuse:
    run([sys.executable, '-u', 'rerank_kosis_tables_with_sqlite_metadata.py',
         '--claims', CLAIMS, '--table-candidates', TABLES,
         '--metadata-db', DB, '--output', RAW,
         '--device', 'cuda', '--batch-size', '8', '--top-k', '10',
         '--metadata-weight', '0.5'])
    RAW_META.write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding='utf-8')
print('BGE scores:', 'reused' if reuse else 'generated', '| rows =', sum(1 for _ in open(RAW, encoding='utf-8-sig')) - 1)
"""),
        code(r"""# 6. 가중치 7개 × 좌표 선택 3개 = 21개 개발 평가
WEIGHTS = [0.00, 0.20, 0.35, 0.50, 0.65, 0.80, 1.00]
MODES = ['joint', 'table_top3', 'table_locked']
TRUSTED = ROOT / 'data/dev/trusted_pass_119.csv'
FULL = ROOT / 'data/gold/mcp_full_gold_200.csv'
SWEEP = RUN / 'sweep'
rows = []

for weight in WEIGHTS:
    weight_id = f'w{int(round(weight * 100)):03d}'
    weighted = SWEEP / weight_id / 'table_candidates.csv'
    run([sys.executable, 'apply_kosis_metadata_reranker_weight.py',
         '--input', RAW, '--output', weighted, '--weight', weight])
    for mode in MODES:
        variant = SWEEP / weight_id / mode
        coord = variant / 'coordinate_candidates.csv'
        selected = variant / 'selected.csv'
        failures = variant / 'failures.csv'
        run([sys.executable, 'kosis_sqlite_resolver.py',
             '--claims', CLAIMS, '--table-candidates', weighted,
             '--metadata-db', DB, '--candidate-output', coord,
             '--selected-output', selected, '--failure-output', failures,
             '--table-top-k', '10', '--item-top-k', '10',
             '--selection-mode', mode])
        trusted_dir = variant / 'evaluation_trusted119'
        full_dir = variant / 'evaluation_full200'
        run([sys.executable, 'evaluate_mcp_gold_200_mapping.py',
             '--gold', TRUSTED, '--candidates', coord, '--mapped', selected,
             '--output-dir', trusted_dir, '--ks', '1', '3', '5', '10', '20', '50'])
        run([sys.executable, 'evaluate_mcp_gold_200_mapping.py',
             '--gold', FULL, '--candidates', coord, '--mapped', selected,
             '--output-dir', full_dir, '--ks', '1', '3', '5', '10', '20', '50'])
        trusted = read_json(trusted_dir / 'summary.json')
        full = read_json(full_dir / 'summary.json')
        rows.append({
            'weight': weight, 'weight_id': weight_id, 'selection_mode': mode,
            'trusted_full_mapping_accuracy': trusted['full_mapping_accuracy'],
            'trusted_item_accuracy': trusted['item_accuracy'],
            'trusted_table_accuracy': trusted['table_accuracy'],
            'trusted_table_recall_at_10': trusted['table_recall_at_10'],
            'trusted_coordinate_recall_at_10': trusted['coordinate_recall_at_10'],
            'full200_full_mapping_accuracy_diagnostic': full['full_mapping_accuracy'],
            'full200_item_accuracy_diagnostic': full['item_accuracy'],
            'full200_table_accuracy_diagnostic': full['table_accuracy'],
            'variant_dir': str(variant),
        })
        print(rows[-1])
"""),
        code(r"""# 7. 최적 구성 선택 및 표 출력
rows.sort(key=lambda row: (
    row['trusted_full_mapping_accuracy'],
    row['trusted_item_accuracy'],
    row['trusted_table_accuracy'],
    row['trusted_coordinate_recall_at_10'],
), reverse=True)
best = rows[0]

summary_csv = RUN / 'v11_weight_selection_sweep.csv'
with summary_csv.open('w', encoding='utf-8-sig', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
(RUN / 'best_config.json').write_text(json.dumps(best, ensure_ascii=False, indent=2), encoding='utf-8')

import pandas as pd
display(pd.DataFrame(rows).head(21))
print('\nBEST')
print(json.dumps(best, ensure_ascii=False, indent=2))
"""),
        code(r"""# 8. 필요한 결과만 ZIP으로 다운로드
RESULT = Path('/content/mcp_gold_200_v11_metadata_reranker_gpu_results')
if RESULT.exists():
    shutil.rmtree(RESULT)
RESULT.mkdir(parents=True)
shutil.copy2(RUN / 'v11_weight_selection_sweep.csv', RESULT)
shutil.copy2(RUN / 'best_config.json', RESULT)
shutil.copy2(RAW_META, RESULT)
shutil.copy2(ROOT / 'data/dev/gold_audit_summary.json', RESULT)

best_variant = Path(best['variant_dir'])
best_out = RESULT / 'best_variant'
shutil.copytree(best_variant, best_out)
best_weighted = SWEEP / best['weight_id'] / 'table_candidates.csv'
shutil.copy2(best_weighted, RESULT / 'best_table_candidates.csv')

run_summary = {
    'architecture': 'vector Top-10 -> SQLite metadata BGE reranker -> SQLite ITEM/OBJ resolver',
    'bge_inference_runs': 1,
    'weights': WEIGHTS,
    'selection_modes': MODES,
    'trusted_gold_rows': 119,
    'full_gold_rows_diagnostic_only': 200,
    'best': best,
    'raw_score_sha256': file_hash(RAW),
}
(RESULT / 'gpu_run_summary.json').write_text(json.dumps(run_summary, ensure_ascii=False, indent=2), encoding='utf-8')
archive = shutil.make_archive('/content/mcp_gold_200_v11_metadata_reranker_gpu_results', 'zip', RESULT)
print('다운로드:', archive)
files.download(archive)
"""),
        md("""## 다음 단계

다운로드된 `mcp_gold_200_v11_metadata_reranker_gpu_results.zip`을 Codex에 첨부하세요.
중단되면 같은 노트북을 다시 실행해도 Google Drive의 BGE 점수 체크포인트를 재사용합니다.
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
    hashes = {name: sha256(path) for name, path in sorted(files.items())}
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "MCP gold 200 v11 SQLite metadata reranker GPU development sweep",
        "secrets_included": False,
        "api_calls_required": False,
        "trusted_gold_rows": 119,
        "full_gold_rows": 200,
        "weights": [0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0],
        "selection_modes": ["joint", "table_top3", "table_locked"],
        "files": hashes,
    }
    manifest["payload_sha256"] = hashlib.sha256(
        json.dumps(hashes, sort_keys=True).encode("utf-8")
    ).hexdigest()
    OUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BUNDLE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, name)
        archive.writestr("bundle_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    manifest["bundle_sha256"] = sha256(BUNDLE)
    manifest["bundle_size_bytes"] = BUNDLE.stat().st_size
    (OUT / "bundle_build_summary.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    files = source_files()
    build_notebook()
    manifest = build_bundle(files)
    print(json.dumps({
        "notebook": str(NOTEBOOK),
        "bundle": str(BUNDLE),
        "manifest": manifest,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
