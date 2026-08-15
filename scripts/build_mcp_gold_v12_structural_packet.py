#!/usr/bin/env python3
"""Build the v12 Top-20 metadata-reranker + SQLite structural packet."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/mcp_gold_200_v12_structural"
NOTEBOOK = ROOT / "notebooks/mcp_gold_200_v12_structural_gpu_colab.ipynb"
BUNDLE = OUT / "mcp_gold_200_v12_structural_colab_input_bundle.zip"


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
    names = (
        "apply_kosis_metadata_reranker_weight.py",
        "apply_kosis_structural_table_policy.py",
        "audit_mcp_gold_coordinate_consistency.py",
        "audit_mcp_gold_semantic_consistency.py",
        "evaluate_mcp_gold_200_mapping.py",
        "kosis_indicator_table_match.py",
        "kosis_meta_coordinates.py",
        "kosis_sqlite_metadata.py",
        "kosis_sqlite_resolver.py",
        "prepare_kosis_mapping_input.py",
        "rerank_kosis_tables_with_sqlite_metadata.py",
        "rerank_mcp_gold_200_table_candidates.py",
        "search_mcp_gold_200_chroma_bge.py",
        "select_mcp_gold_200_two_stage_coordinates.py",
    )
    files = {name: ROOT / name for name in names}
    files.update({
        "data/dev/enriched_inputs.csv": ROOT / "outputs/mcp_gold_200_v11_metadata_reranker/input_bundle/data/dev/enriched_inputs.csv",
        "data/dev/table_candidates.csv": ROOT / "outputs/mcp_gold_200_v11_metadata_reranker/input_bundle/data/dev/table_candidates.csv",
        "data/dev/semantic_trusted_42.csv": ROOT / "outputs/mcp_gold_200_v11_metadata_reranker/semantic_trusted_42.csv",
        "data/dev/semantic_trusted_v2.csv": ROOT / "outputs/mcp_gold_200_v11_metadata_reranker/semantic_trusted_v2.csv",
        "data/gold/mcp_full_gold_200.csv": ROOT / "data/gold/mcp_full_gold_200.csv",
        "data/index/kosis_metadata.sqlite": OUT / "kosis_metadata.sqlite",
        "data/index/periodicity_merge_summary.json": OUT / "periodicity_merge_summary.json",
    })
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing packet inputs: {missing}")
    return files


def build_notebook() -> None:
    cells = [
        md("""# MCP Gold 200 v12 — Top-20 + SQLite structural policy

- BGE 메타데이터 Reranker 입력을 Top-10에서 Top-20으로 확장합니다.
- 공식 수록주기·OBJ 지원·미요청 계절조정/모집단 범위를 SQLite에서 검사합니다.
- 구조 가중치 `0.30, 0.50, 0.80, 1.00`을 비교합니다.
- 개발 선택은 의미 감사 42건으로 하되, 더 보수적인 23건도 함께 보고합니다.
- 전체 200건은 골드 오염 진단용으로만 평가합니다.
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
assert len(bundles) == 1, 'v12 입력 ZIP 하나만 업로드하세요.'
ROOT = Path('/content/mcp_gold_v12_structural')
if ROOT.exists(): shutil.rmtree(ROOT)
ROOT.mkdir(parents=True)
with zipfile.ZipFile(io.BytesIO(uploaded[bundles[0]])) as archive:
    for info in archive.infolist():
        parts = [p for p in info.filename.replace('\\', '/').split('/') if p not in {'', '.'}]
        assert '..' not in parts, f'안전하지 않은 ZIP 경로: {info.filename}'
        target = ROOT.joinpath(*parts)
        if info.is_dir(): target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
assert (ROOT / 'data/dev/enriched_inputs.csv').is_file(), '번들 해제 실패'
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
drive.mount('/content/drive')
RUN = Path('/content/drive/MyDrive/kosis_mcp_gold_v12_structural/run')
RUN.mkdir(parents=True, exist_ok=True)

def run(args):
    cmd = [str(v) for v in args]
    print('\n$', ' '.join(cmd[:6]), '...', flush=True)
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert p.stdout is not None
    for line in p.stdout: print(line, end='', flush=True)
    rc = p.wait()
    if rc: raise subprocess.CalledProcessError(rc, cmd)

def file_hash(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_json(path): return json.loads(Path(path).read_text(encoding='utf-8'))
print('ROOT =', ROOT, '| RUN =', RUN)
"""),
        code(r"""# 3. 번들 무결성 확인 및 의존성 설치
manifest = read_json(ROOT / 'bundle_manifest.json')
for relative, expected in manifest['files'].items():
    assert file_hash(ROOT / relative) == expected, f'해시 불일치: {relative}'
%pip install -q "transformers>=4.45,<6"
import torch
assert torch.cuda.is_available(), 'CUDA를 사용할 수 없습니다.'
print('verified files =', len(manifest['files']), '| GPU =', torch.cuda.get_device_name(0))
"""),
        code(r"""# 4. BGE 메타데이터 Top-20 점수 생성 또는 재사용
CLAIMS = ROOT / 'data/dev/enriched_inputs.csv'
TABLES = ROOT / 'data/dev/table_candidates.csv'
DB = ROOT / 'data/index/kosis_metadata.sqlite'
RAW = RUN / 'metadata_reranker_scored_top20.csv'
RAW_META = RUN / 'metadata_reranker_scored_top20.manifest.json'
expected = {'claims_sha256': file_hash(CLAIMS), 'tables_sha256': file_hash(TABLES),
            'sqlite_sha256': file_hash(DB), 'model': 'BAAI/bge-reranker-v2-m3', 'top_k': 20}
reuse = RAW.is_file() and RAW_META.is_file() and read_json(RAW_META) == expected
if not reuse:
    run([sys.executable, '-u', 'rerank_kosis_tables_with_sqlite_metadata.py',
         '--claims', CLAIMS, '--table-candidates', TABLES, '--metadata-db', DB,
         '--output', RAW, '--device', 'cuda', '--batch-size', '8', '--top-k', '20',
         '--metadata-weight', '0.5'])
    RAW_META.write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding='utf-8')
print('BGE Top-20:', 'reused' if reuse else 'generated')
"""),
        code(r"""# 5. BGE 가중치와 SQLite 구조 가중치 비교
BGE_WEIGHTS = [0.00, 0.35, 1.00]
STRUCT_WEIGHTS = [0.30, 0.50, 0.80, 1.00]
GOLD42 = ROOT / 'data/dev/semantic_trusted_42.csv'
GOLD23 = ROOT / 'data/dev/semantic_trusted_v2.csv'
FULL = ROOT / 'data/gold/mcp_full_gold_200.csv'
rows = []
for bw in BGE_WEIGHTS:
    bid = f'b{int(round(bw*100)):03d}'
    weighted = RUN / 'sweep' / bid / 'metadata_weighted.csv'
    run([sys.executable, 'apply_kosis_metadata_reranker_weight.py',
         '--input', RAW, '--output', weighted, '--weight', bw])
    for sw in STRUCT_WEIGHTS:
        sid = f's{int(round(sw*100)):03d}'
        variant = RUN / 'sweep' / bid / sid
        tables = variant / 'tables.csv'
        coords = variant / 'coordinates.csv'
        selected = variant / 'selected.csv'
        run([sys.executable, 'apply_kosis_structural_table_policy.py', '--claims', CLAIMS,
             '--candidates', weighted, '--metadata-db', DB, '--output', tables, '--weight', sw])
        run([sys.executable, 'kosis_sqlite_resolver.py', '--claims', CLAIMS,
             '--table-candidates', tables, '--metadata-db', DB,
             '--candidate-output', coords, '--selected-output', selected,
             '--failure-output', variant/'failures.csv', '--table-top-k', '20',
             '--item-top-k', '10', '--selection-mode', 'joint'])
        summaries = {}
        for label, gold in [('audit42', GOLD42), ('strict23', GOLD23), ('full200', FULL)]:
            out = variant / f'eval_{label}'
            run([sys.executable, 'evaluate_mcp_gold_200_mapping.py', '--gold', gold,
                 '--candidates', coords, '--mapped', selected, '--output-dir', out,
                 '--ks', '1', '3', '5', '10', '20'])
            summaries[label] = read_json(out/'summary.json')
        rows.append({
            'bge_weight': bw, 'structural_weight': sw,
            'audit42_full': summaries['audit42']['full_mapping_accuracy'],
            'audit42_table': summaries['audit42']['table_accuracy'],
            'audit42_item': summaries['audit42']['item_accuracy'],
            'audit42_top10': summaries['audit42']['table_recall_at_10'],
            'strict23_full': summaries['strict23']['full_mapping_accuracy'],
            'full200_diagnostic': summaries['full200']['full_mapping_accuracy'],
            'variant': str(variant),
        })
        print(rows[-1])
"""),
        code(r"""# 6. 최적 구성 선택 및 결과 ZIP
rows.sort(key=lambda r: (r['audit42_full'], r['audit42_item'], r['audit42_table'],
                         r['audit42_top10'], r['strict23_full']), reverse=True)
best = rows[0]
with (RUN/'v12_sweep.csv').open('w', encoding='utf-8-sig', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
(RUN/'best_config.json').write_text(json.dumps(best, ensure_ascii=False, indent=2), encoding='utf-8')
import pandas as pd
display(pd.DataFrame(rows)); print(json.dumps(best, ensure_ascii=False, indent=2))

RESULT = Path('/content/mcp_gold_200_v12_structural_gpu_results')
if RESULT.exists(): shutil.rmtree(RESULT)
RESULT.mkdir()
shutil.copy2(RUN/'v12_sweep.csv', RESULT)
shutil.copy2(RUN/'best_config.json', RESULT)
shutil.copy2(RAW_META, RESULT)
shutil.copytree(Path(best['variant']), RESULT/'best_variant')
archive = shutil.make_archive('/content/mcp_gold_200_v12_structural_gpu_results', 'zip', RESULT)
print('다운로드:', archive); files.download(archive)
"""),
        md("""## 다음 단계

완료 후 `mcp_gold_200_v12_structural_gpu_results.zip`을 Codex에 첨부하세요.
중단 후 재실행해도 Google Drive의 Top-20 BGE 점수를 재사용합니다.
"""),
    ]
    notebook = {
        "cells": cells,
        "metadata": {
            "accelerator": "GPU",
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4, "nbformat_minor": 5,
    }
    NOTEBOOK.parent.mkdir(parents=True, exist_ok=True)
    NOTEBOOK.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def build_bundle(files: dict[str, Path]) -> dict[str, object]:
    hashes = {name: sha256(path) for name, path in sorted(files.items())}
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "v12 Top-20 metadata reranker and SQLite structural policy sweep",
        "secrets_included": False,
        "api_calls_required": False,
        "files": hashes,
    }
    manifest["payload_sha256"] = hashlib.sha256(
        json.dumps(hashes, sort_keys=True).encode("utf-8")
    ).hexdigest()
    OUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BUNDLE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(files.items()): archive.write(path, name)
        archive.writestr("bundle_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    manifest["bundle_sha256"] = sha256(BUNDLE)
    manifest["bundle_size_bytes"] = BUNDLE.stat().st_size
    (OUT/"bundle_build_summary.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    files = source_files()
    build_notebook()
    manifest = build_bundle(files)
    print(json.dumps({"notebook": str(NOTEBOOK), "bundle": str(BUNDLE),
                      "manifest": manifest}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
