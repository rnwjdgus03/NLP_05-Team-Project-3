#!/usr/bin/env python3
"""Generate the Colab GPU notebook for gold-200 lexical/BGE evaluation."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "notebooks" / "mcp_gold_200_chroma_bge_gpu_colab.ipynb"


def markdown(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def code(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


cells = [
    markdown("""# MCP 골드 200 v6 — 구조 우선 좌표 shortlist + Top-5/Top-10 A/B

KOSIS 표 107,138개를 대상으로 다음 세 경로를 한 번에 비교한다.

1. lexical Top-50 기준선
2. Chroma/BGE-M3 dense Top-20 감사 후보
3. lexical 후보를 BGE cross-encoder로 재정렬한 최종 Top-20

검색에는 `mcp_full_gold_200_inputs.csv`만 사용하고 `gold_*` 정답 좌표는 평가 단계에서만 읽는다.
Colab에서 GPU 런타임을 선택하고 셀을 위에서 아래로 실행한 뒤 새 v6 번들을 업로드한다.
"""),
    code("""# 1. GPU 확인
import subprocess
gpu = subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True, check=True)
print(gpu.stdout.strip())
assert 'GPU' in gpu.stdout, 'Colab 런타임을 GPU로 변경하세요.'
"""),
    code("""# 2. Drive 연결 및 v6 번들 업로드
from google.colab import drive, files
from pathlib import Path
import io, os, shutil, sys, zipfile

drive.mount('/content/drive', force_remount=False)
os.chdir('/content')
uploaded = files.upload()
bundle_names = [name for name in uploaded if name.endswith('.zip')]
assert len(bundle_names) == 1, 'v6 Colab 번들 ZIP 하나만 업로드하세요.'

ROOT = Path('/content/mcp_gold_200_gpu_v6')
if ROOT.exists():
    shutil.rmtree(ROOT)
ROOT.mkdir(parents=True)
with zipfile.ZipFile(io.BytesIO(uploaded[bundle_names[0]])) as archive:
    for info in archive.infolist():
        parts = [p for p in info.filename.replace('\\\\', '/').split('/') if p not in {'', '.'}]
        assert '..' not in parts, f'안전하지 않은 ZIP 경로: {info.filename}'
        target = ROOT.joinpath(*parts)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))

DRIVE_ROOT = Path('/content/drive/MyDrive/mcp_gold_200_chroma_bge')
SEM = DRIVE_ROOT / 'kosis_bge_m3'
LOCAL_INDEX = ROOT / 'data/indexes'
TABLE_CHROMA = LOCAL_INDEX / 'kosis_table_chroma'
COORD_CHROMA = LOCAL_INDEX / 'kosis_gold10_meta_chroma'
OUT = ROOT / 'outputs/mcp_gold_200_coordinate_ab_v6'
for path in (DRIVE_ROOT, LOCAL_INDEX, OUT):
    path.mkdir(parents=True, exist_ok=True)
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
print('project =', ROOT)
print('embedding checkpoint =', SEM)
"""),
    code("""# 3. 의존성 설치
%pip install -q -r requirements-ml.txt
import torch, chromadb, sentence_transformers
assert torch.cuda.is_available(), 'CUDA PyTorch를 사용할 수 없습니다.'
props = torch.cuda.get_device_properties(0)
GPU_BATCH = 64 if props.total_memory >= 14 * 1024**3 else 32
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
print('torch =', torch.__version__)
print('GPU =', props.name, '| VRAM GiB =', round(props.total_memory / 1024**3, 1))
print('batch =', GPU_BATCH)
"""),
    code("""# 4. 실행 도우미와 번들 무결성 검증
import csv, hashlib, json, subprocess

def run(args):
    args = [str(value) for value in args]
    print('RUN:', ' '.join(args))
    subprocess.run(args, cwd=ROOT, check=True)

def csv_rows(path):
    with open(path, encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))

def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

manifest = json.loads((ROOT / 'bundle_manifest.json').read_text(encoding='utf-8'))
assert manifest['bundle_version'] == 6
for rel, expected in manifest['files'].items():
    assert sha256(ROOT / rel) == expected, f'해시 불일치: {rel}'
print('bundle files verified =', len(manifest['files']))
"""),
    code("""# 5. 골드 격리, 단위 선택, 기간 구조화
RAW_INPUTS = ROOT / 'data/gold/mcp_full_gold_200_inputs.csv'
INPUTS = OUT / 'enriched_inputs.csv'
GOLD = ROOT / 'data/gold/mcp_full_gold_200.csv'
raw_inputs = csv_rows(RAW_INPUTS)
gold = csv_rows(GOLD)
assert len(raw_inputs) == 200 and len(gold) == 200
forbidden = {field for field in raw_inputs[0] if field.startswith('gold_') and field != 'gold_id'}
assert not forbidden, forbidden
assert manifest['gold_used_for_retrieval'] is False
run([sys.executable, 'enrich_mcp_gold_200_inputs.py',
     '--input', RAW_INPUTS,
     '--output', INPUTS,
     '--stats', OUT / 'period_extraction_stats.json'])
inputs = csv_rows(INPUTS)
assert len(inputs) == 200
enriched_forbidden = {field for field in inputs[0] if field.startswith('gold_') and field != 'gold_id'}
assert not enriched_forbidden, enriched_forbidden
quality_counts = {status: sum(row['input_quality_status'] == status for row in inputs)
                  for status in {row['input_quality_status'] for row in inputs}}
assert quality_counts == {'READY': 194, 'NEEDS_INPUT_REVIEW': 6}, quality_counts
print('gold-free enriched inputs =', len(inputs), '| quality =', quality_counts,
      '| evaluation gold =', len(gold))
"""),
    code("""# 6. BGE-M3 표 임베딩 생성 또는 Drive 체크포인트 재사용
run([sys.executable, 'kosis_build_embedding_index.py',
     '--table-index', 'data/reference/kosis_table_summary.csv',
     '--out-dir', SEM,
     '--embedding-model', 'BAAI/bge-m3',
     '--batch-size', str(GPU_BATCH),
     '--device', 'cuda'])
semantic_manifest = json.loads((SEM / 'manifest.json').read_text(encoding='utf-8'))
assert semantic_manifest['table_count'] == 107138
assert semantic_manifest['dimension'] == 1024
print(json.dumps(semantic_manifest, ensure_ascii=False, indent=2))
"""),
    code("""# 7. Chroma kosis_table 생성
run([sys.executable, 'kosis_load_chroma_table_index.py',
     '--semantic-index', SEM,
     '--persist-dir', TABLE_CHROMA,
     '--collection', 'kosis_table',
     '--batch-size', '1000',
     '--reset'])
table_manifest = json.loads((TABLE_CHROMA / 'chroma_manifest.json').read_text(encoding='utf-8'))
assert table_manifest['document_count'] == 107138
print(json.dumps(table_manifest, ensure_ascii=False, indent=2))
"""),
    code("""# 8. lexical 후보, Chroma dense 후보, BGE 재정렬 후보 생성
LEXICAL_TABLE_CANDIDATES = OUT / 'lexical_table_candidates.csv'
DENSE_TABLE_CANDIDATES = OUT / 'dense_table_candidates.csv'
TABLE_CANDIDATES = OUT / 'table_candidates.csv'

run([sys.executable, 'build_mcp_gold_200_lexical_table_candidates.py',
     '--input', INPUTS,
     '--table-index', 'data/reference/kosis_table_summary.csv',
     '--output', LEXICAL_TABLE_CANDIDATES,
     '--top-k', '50'])
run([sys.executable, 'search_mcp_gold_200_chroma_bge.py',
     '--claims', INPUTS,
     '--persist-dir', TABLE_CHROMA,
     '--collection', 'kosis_table',
     '--output', DENSE_TABLE_CANDIDATES,
     '--top-k', '20',
     '--batch-size', str(GPU_BATCH),
     '--device', 'cuda'])
run([sys.executable, 'rerank_mcp_gold_200_table_candidates.py',
     '--claims', INPUTS,
     '--lexical-candidates', LEXICAL_TABLE_CANDIDATES,
     '--dense-candidates', DENSE_TABLE_CANDIDATES,
     '--output', TABLE_CANDIDATES,
     '--lexical-top-k', '50',
     '--dense-top-k', '20',
     '--final-top-k', '20',
     '--reranker-model', 'BAAI/bge-reranker-v2-m3',
     '--device', 'cuda',
     '--batch-size', str(GPU_BATCH)])

assert len(csv_rows(LEXICAL_TABLE_CANDIDATES)) == 10000
assert len(csv_rows(DENSE_TABLE_CANDIDATES)) == 4000
assert len(csv_rows(TABLE_CANDIDATES)) == 4000
print('candidate files complete')
"""),
    code("""# 9. lexical 기준선과 BGE 재정렬 Recall@K 비교
LEXICAL_EVAL = OUT / 'lexical_retrieval_evaluation'
RETRIEVAL_EVAL = OUT / 'retrieval_evaluation'
run([sys.executable, 'evaluate_mcp_gold_200_mapping.py',
     '--gold', GOLD,
     '--candidates', LEXICAL_TABLE_CANDIDATES,
     '--input-fixture', INPUTS,
     '--output-dir', LEXICAL_EVAL,
     '--ks', '1', '3', '5', '10', '20', '50'])
run([sys.executable, 'evaluate_mcp_gold_200_mapping.py',
     '--gold', GOLD,
     '--candidates', TABLE_CANDIDATES,
     '--input-fixture', INPUTS,
     '--output-dir', RETRIEVAL_EVAL])
lexical_summary = json.loads((LEXICAL_EVAL / 'summary.json').read_text(encoding='utf-8'))
retrieval_summary = json.loads((RETRIEVAL_EVAL / 'summary.json').read_text(encoding='utf-8'))
assert lexical_summary['table_recall_at_20'] >= 0.80, lexical_summary
print('LEXICAL:', json.dumps(lexical_summary, ensure_ascii=False, indent=2))
print('RERANKED:', json.dumps(retrieval_summary, ensure_ascii=False, indent=2))
"""),
    code("""# 10. ITEM·OBJ 좌표 Chroma 인덱스 생성
run([sys.executable, 'kosis_build_chroma_meta_index.py',
     '--meta-index', 'data/reference/kosis_gold10_meta_index.csv',
     '--persist-dir', COORD_CHROMA,
     '--collection', 'kosis_gold10_coordinates',
     '--embedding-model', 'BAAI/bge-m3',
     '--device', 'cuda',
     '--batch-size', str(GPU_BATCH),
     '--axis-value-limit', '6000',
     '--max-coordinates-per-table', '12000',
     '--reset'])
coord_manifest = json.loads((COORD_CHROMA / 'chroma_manifest.json').read_text(encoding='utf-8'))
assert coord_manifest['document_count'] == 12721
print(json.dumps(coord_manifest, ensure_ascii=False, indent=2))
"""),
    code("""# 11. 최종 표 Top-5 내부 ITEM·OBJ 좌표 검색
MAPPED = OUT / 'coordinate_candidates.csv'
STATS = OUT / 'coordinate_search_stats.csv'
run([sys.executable, 'kosis_chroma_hybrid_search.py',
     '--claims', INPUTS,
     '--table-candidates', TABLE_CANDIDATES,
     '--output', MAPPED,
     '--persist-dir', COORD_CHROMA,
     '--collection', 'kosis_gold10_coordinates',
     '--embedding-model', 'BAAI/bge-m3',
     '--reranker-model', 'BAAI/bge-reranker-v2-m3',
     '--device', 'cuda',
     '--table-top-k', '5',
     '--dense-top-k', '50',
     '--lexical-top-k', '50',
     '--rerank-top-k', '20',
     '--final-top-k', '10',
     '--stats-output', STATS])
MAPPED_TOP5_RAW = MAPPED
MAPPED_TOP10_RAW = OUT / 'coordinate_candidates_top10.csv'
STATS_TOP10 = OUT / 'coordinate_search_stats_top10.csv'
run([sys.executable, 'kosis_chroma_hybrid_search.py',
     '--claims', INPUTS,
     '--table-candidates', TABLE_CANDIDATES,
     '--output', MAPPED_TOP10_RAW,
     '--persist-dir', COORD_CHROMA,
     '--collection', 'kosis_gold10_coordinates',
     '--embedding-model', 'BAAI/bge-m3',
     '--reranker-model', 'BAAI/bge-reranker-v2-m3',
     '--device', 'cuda',
     '--table-top-k', '10',
     '--dense-top-k', '50',
     '--lexical-top-k', '50',
     '--rerank-top-k', '20',
     '--final-top-k', '10',
     '--stats-output', STATS_TOP10])

MAPPED_TOP5 = OUT / 'selected_coordinates_top5.csv'
MAPPED_TOP10 = OUT / 'selected_coordinates_top10.csv'
for source, target in [(MAPPED_TOP5_RAW, MAPPED_TOP5), (MAPPED_TOP10_RAW, MAPPED_TOP10)]:
    run([sys.executable, 'select_mcp_gold_200_two_stage_coordinates.py',
         '--claims', INPUTS,
         '--candidates', source,
         '--output', target,
         '--item-top-k', '3'])
print('raw top5/top10 rows =', len(csv_rows(MAPPED_TOP5_RAW)), len(csv_rows(MAPPED_TOP10_RAW)))
print('selected top5/top10 rows =', len(csv_rows(MAPPED_TOP5)), len(csv_rows(MAPPED_TOP10)))
"""),
    code("""# 12. 전체 매핑 평가
FULL_EVAL = OUT / 'full_mapping_evaluation'
run([sys.executable, 'evaluate_mcp_gold_200_mapping.py',
     '--gold', GOLD,
     '--candidates', TABLE_CANDIDATES,
     '--mapped', MAPPED,
     '--input-fixture', INPUTS,
     '--output-dir', FULL_EVAL])
mapping_summary = json.loads((FULL_EVAL / 'summary.json').read_text(encoding='utf-8'))
TOP5_EVAL = OUT / 'two_stage_top5_evaluation'
TOP10_EVAL = OUT / 'two_stage_top10_evaluation'
for mapped, evaluation in [(MAPPED_TOP5, TOP5_EVAL), (MAPPED_TOP10, TOP10_EVAL)]:
    run([sys.executable, 'evaluate_mcp_gold_200_mapping.py',
         '--gold', GOLD,
         '--candidates', TABLE_CANDIDATES,
         '--mapped', mapped,
         '--input-fixture', INPUTS,
         '--output-dir', evaluation])
top5_summary = json.loads((TOP5_EVAL / 'summary.json').read_text(encoding='utf-8'))
top10_summary = json.loads((TOP10_EVAL / 'summary.json').read_text(encoding='utf-8'))
AB_EVAL = OUT / 'top5_vs_top10_ab'
run([sys.executable, 'compare_mcp_gold_200_coordinate_ab.py',
     '--top5-summary', TOP5_EVAL / 'summary.json',
     '--top10-summary', TOP10_EVAL / 'summary.json',
     '--output-dir', AB_EVAL])
print('RAW TOP5:', json.dumps(mapping_summary, ensure_ascii=False, indent=2))
print('TWO-STAGE TOP5:', json.dumps(top5_summary, ensure_ascii=False, indent=2))
print('TWO-STAGE TOP10:', json.dumps(top10_summary, ensure_ascii=False, indent=2))
"""),
    code("""# 13. 핵심 지표
def norm_missing(value):
    value = str(value or '').strip()
    return '' if value in {'', '-', 'None', 'nan', 'NaN', 'N/A', 'NA'} else value

gold_by_id = {row['gold_id']: row for row in gold}
input_by_id = {row['gold_id']: row for row in inputs}
period_field_accuracy = {}
for predicted, expected in [
    ('prd_se', 'gold_prd_se'),
    ('period', 'gold_period'),
    ('previous_period', 'gold_previous_period'),
]:
    period_field_accuracy[predicted] = sum(
        norm_missing(input_by_id[key][predicted]) == norm_missing(gold_by_id[key][expected])
        for key in gold_by_id
    ) / len(gold_by_id)
period_group_accuracy = sum(
    all(
        norm_missing(input_by_id[key][predicted]) == norm_missing(gold_by_id[key][expected])
        for predicted, expected in [
            ('prd_se', 'gold_prd_se'),
            ('period', 'gold_period'),
            ('previous_period', 'gold_previous_period'),
        ]
    )
    for key in gold_by_id
) / len(gold_by_id)

metrics = {
    'scorable_rows': retrieval_summary.get('scorable_rows'),
    'needs_input_review_rows': retrieval_summary.get('needs_input_review_rows'),
    'lexical_table_recall@1': lexical_summary.get('table_recall_at_1'),
    'lexical_table_recall@5': lexical_summary.get('table_recall_at_5'),
    'lexical_table_recall@20': lexical_summary.get('table_recall_at_20'),
    'lexical_table_recall@50': lexical_summary.get('table_recall_at_50'),
    'reranked_table_recall@1': retrieval_summary.get('table_recall_at_1'),
    'reranked_table_recall@5': retrieval_summary.get('table_recall_at_5'),
    'reranked_table_recall@20': retrieval_summary.get('table_recall_at_20'),
    'reranked_table_recall@20_scorable': retrieval_summary.get('table_recall_at_20_scorable'),
    'reranker_delta@1': retrieval_summary.get('table_recall_at_1') - lexical_summary.get('table_recall_at_1'),
    'reranker_delta@5': retrieval_summary.get('table_recall_at_5') - lexical_summary.get('table_recall_at_5'),
    'reranker_delta@20': retrieval_summary.get('table_recall_at_20') - lexical_summary.get('table_recall_at_20'),
    'input_prd_se_accuracy': period_field_accuracy['prd_se'],
    'input_period_accuracy': period_field_accuracy['period'],
    'input_previous_period_accuracy': period_field_accuracy['previous_period'],
    'input_period_group_accuracy': period_group_accuracy,
    'raw_top5_mapping_coverage': mapping_summary.get('mapping_coverage'),
    'raw_top5_table_accuracy': mapping_summary.get('table_accuracy'),
    'raw_top5_item_accuracy': mapping_summary.get('item_accuracy'),
    'raw_top5_full_mapping_accuracy': mapping_summary.get('full_mapping_accuracy'),
    'two_stage_top5_mapping_coverage': top5_summary.get('mapping_coverage'),
    'two_stage_top5_table_accuracy': top5_summary.get('table_accuracy'),
    'two_stage_top5_item_accuracy': top5_summary.get('item_accuracy'),
    'two_stage_top5_period_accuracy': top5_summary.get('period_accuracy'),
    'two_stage_top5_full_mapping_accuracy': top5_summary.get('full_mapping_accuracy'),
    'two_stage_top5_full_mapping_accuracy_scorable': top5_summary.get('full_mapping_accuracy_scorable'),
    'two_stage_top10_mapping_coverage': top10_summary.get('mapping_coverage'),
    'two_stage_top10_table_accuracy': top10_summary.get('table_accuracy'),
    'two_stage_top10_item_accuracy': top10_summary.get('item_accuracy'),
    'two_stage_top10_period_accuracy': top10_summary.get('period_accuracy'),
    'two_stage_top10_full_mapping_accuracy': top10_summary.get('full_mapping_accuracy'),
    'two_stage_top10_full_mapping_accuracy_scorable': top10_summary.get('full_mapping_accuracy_scorable'),
    'top10_minus_top5_table_accuracy': top10_summary.get('table_accuracy') - top5_summary.get('table_accuracy'),
    'top10_minus_top5_item_accuracy': top10_summary.get('item_accuracy') - top5_summary.get('item_accuracy'),
    'top10_minus_top5_full_mapping_accuracy': top10_summary.get('full_mapping_accuracy') - top5_summary.get('full_mapping_accuracy'),
}
print(json.dumps(metrics, ensure_ascii=False, indent=2))
print('주의: 200건은 규칙 개발용 auto-gold입니다. scorable 지표와 별도 holdout을 함께 보세요.')
"""),
    code("""# 14. 결과 ZIP을 Drive에 저장하고 다운로드
from datetime import datetime, timezone

for source, name in [
    (SEM / 'manifest.json', 'semantic_manifest.json'),
    (TABLE_CHROMA / 'chroma_manifest.json', 'table_chroma_manifest.json'),
    (COORD_CHROMA / 'chroma_manifest.json', 'coordinate_chroma_manifest.json'),
]:
    shutil.copy2(source, OUT / name)
(OUT / 'final_metrics.json').write_text(
    json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8'
)
archive = shutil.make_archive('/content/mcp_gold_200_coordinate_ab_gpu_results_v6', 'zip', OUT)
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
drive_copy = DRIVE_ROOT / f'mcp_gold_200_coordinate_ab_gpu_results_v6_{stamp}.zip'
shutil.copy2(archive, drive_copy)
print('Drive saved =', drive_copy)
print('download =', archive)
files.download(archive)
"""),
    markdown("""## 완료

다운로드한 `mcp_gold_200_coordinate_ab_gpu_results_v6.zip`을 Codex 작업에 첨부하면 구조 우선 shortlist와 Top-5/Top-10 ITEM→OBJ 결과를 함께 검증할 수 있다.
"""),
]


notebook = {
    "cells": cells,
    "metadata": {
        "accelerator": "GPU",
        "colab": {"provenance": []},
        "kernelspec": {"display_name": "Python 3", "name": "python3"},
        "language_info": {"name": "python"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"notebook={OUTPUT}")
print(f"cells={len(cells)}")
