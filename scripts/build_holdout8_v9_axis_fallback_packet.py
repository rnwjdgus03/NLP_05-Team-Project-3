#!/usr/bin/env python3
"""Build the holdout8 v9 Colab notebook and its reproducible input bundle."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks/holdout8_stratified48_v9_axis_fallback_gpu_colab.ipynb"
CHECKPOINTS = ROOT / "outputs/holdout8_stratified48_v6/gpu_results_20260809/extracted"
PREREG = ROOT / "docs/holdout8_v9_prereg_20260810.md"
OUTPUT_DIR = ROOT / "outputs/holdout8_stratified48_v9"
BUNDLE = OUTPUT_DIR / "holdout8_v9_axis_fallback_colab_input_bundle.zip"


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
        "cell_type": "code", "execution_count": None, "metadata": {},
        "outputs": [], "source": source.splitlines(keepends=True),
    }


def build_notebook() -> None:
    cells = [
        md("""# Holdout8 v9 — 실제 축 정렬·주기 필터·제한적 Top-10 폴백

v8의 HCX 측정값을 고정하고 검색·좌표 단계만 다시 실행합니다. 입력 번들은 `holdout8_v9_axis_fallback_colab_input_bundle.zip` 하나입니다.
"""),
        code("""# 1. GPU 확인\nimport subprocess\ngpu = subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True, check=True)\nprint(gpu.stdout.strip())\nassert 'GPU' in gpu.stdout, 'Colab 런타임을 GPU로 변경하세요.'\n"""),
        code("""# 2. 번들 업로드와 안전한 해제\nfrom google.colab import files\nfrom pathlib import Path\nimport csv, hashlib, io, json, os, shutil, subprocess, sys, zipfile\n\nos.chdir('/content')\nuploaded = files.upload()\nbundles = [name for name in uploaded if name.endswith('.zip')]\nassert len(bundles) == 1, 'v9 입력 번들 ZIP 하나만 업로드하세요.'\nROOT = Path('/content/holdout8_gpu_v9')\nif ROOT.exists():\n    shutil.rmtree(ROOT)\nROOT.mkdir(parents=True)\nwith zipfile.ZipFile(io.BytesIO(uploaded[bundles[0]])) as archive:\n    for info in archive.infolist():\n        parts = [p for p in info.filename.replace('\\\\', '/').split('/') if p not in {'', '.'}]\n        assert '..' not in parts, f'안전하지 않은 ZIP 경로: {info.filename}'\n        target = ROOT.joinpath(*parts)\n        if info.is_dir():\n            target.mkdir(parents=True, exist_ok=True)\n        else:\n            target.parent.mkdir(parents=True, exist_ok=True)\n            target.write_bytes(archive.read(info))\nassert (ROOT / 'data/holdout8_stratified_articles.csv').is_file(), '번들 구조가 올바르지 않습니다.'\nos.chdir(ROOT)\nsys.path.insert(0, str(ROOT))\nOUT = ROOT / 'outputs/holdout8_stratified48_v9'\nMAP = OUT / '07_mapping_v2'\nSEM = ROOT / 'data/indexes/kosis_bge_m3'\nCHR = ROOT / 'data/indexes/kosis_meta_chroma_holdout8_v9'\nOUT.mkdir(parents=True, exist_ok=True)\n\ndef run(args):\n    cmd = [str(x) for x in args]\n    print('\\n$', ' '.join(cmd[:3]), '...', flush=True)\n    process = subprocess.Popen(cmd, cwd=ROOT, env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)\n    assert process.stdout is not None\n    for line in process.stdout:\n        print(line, end='', flush=True)\n    returncode = process.wait()\n    if returncode:\n        raise subprocess.CalledProcessError(returncode, cmd)\n    return subprocess.CompletedProcess(cmd, returncode)\n\ndef csv_rows(path):\n    with open(path, encoding='utf-8-sig', newline='') as handle:\n        return list(csv.DictReader(handle))\n\nprint('ROOT =', ROOT)\n"""),
        code("""# 3. 의존성 설치\n%pip install -q -r requirements.txt -r requirements-ml.txt\nimport chromadb, pandas as pd, sentence_transformers, torch\nassert torch.cuda.is_available(), 'CUDA를 사용할 수 없습니다.'\nprint('torch', torch.__version__, '| GPU', torch.cuda.get_device_name(0))\n"""),
        code("""# 4. KOSIS API 키\nfrom getpass import getpass\ntry:\n    from google.colab import userdata\nexcept Exception:\n    userdata = None\n\ndef secret(name):\n    value = ''\n    if userdata is not None:\n        try:\n            value = userdata.get(name) or ''\n        except Exception:\n            pass\n    return value or getpass(f'{name}: ')\n\nos.environ['KOSIS_API_KEY'] = secret('KOSIS_API_KEY')\nassert os.environ['KOSIS_API_KEY']\nprint('KOSIS_API_KEY가 메모리에 설정됐습니다.')\n"""),
        code("""# 5. 번들 무결성 검증과 고정 체크포인트 복원\nmanifest = json.loads((ROOT / 'bundle_manifest.json').read_text(encoding='utf-8'))\nfor rel, expected in manifest['files'].items():\n    actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()\n    assert actual == expected, f'해시 불일치: {rel}'\nfor name in ['01_sentences.csv', '03_claim_contexts.csv', '05_hcx_measurements.csv']:\n    shutil.copy2(ROOT / 'data/checkpoints' / name, OUT / name)\narticles = csv_rows(ROOT / 'data/holdout8_stratified_articles.csv')\nmeasurements = csv_rows(OUT / '05_hcx_measurements.csv')\nassert len(articles) == 48 and len(measurements) == 769\nprint('고정 입력:', len(articles), 'articles /', len(measurements), 'measurements')\n"""),
        code("""# 6. KOSIS 표 BGE-M3 인덱스\nrun([sys.executable, 'kosis_build_embedding_index.py', '--table-index', 'data/reference/kosis_table_summary.csv', '--out-dir', SEM, '--batch-size', '16', '--device', 'cuda'])\nassert (SEM / 'manifest.json').is_file()\n"""),
        code("""# 7. 고정 measurement에서 표 후보와 공식 메타 생성\nrun([sys.executable, 'run_kosis_measurement_pipeline.py', '--input', OUT / '05_hcx_measurements.csv', '--table-index', ROOT / 'data/reference/kosis_table_summary.csv', '--semantic-index', SEM, '--out-dir', MAP, '--retrieval-mode', 'hybrid', '--semantic-top-k', '50', '--rerank-top-k', '60', '--top-tables', '20', '--lexical-reserve-k', '10', '--top-rank-for-meta', '20', '--device', 'cuda'])\nREADY = MAP / '05_hcx_measurements_kosis_ready.csv'\nMETA = MAP / '05_hcx_measurements_kosis_meta_index.csv'\nTABLE_CAND = MAP / '05_hcx_measurements_kosis_table_candidates.csv'\nEVAL = MAP / 'evaluation_set.csv'\nrun([sys.executable, 'lock_evaluation_set.py', '--ready', READY, '--output', EVAL, '--excluded-output', MAP / 'evaluation_set_excluded.csv', '--manifest', MAP / 'evaluation_set_manifest.json'])\nprint('evaluation rows =', len(csv_rows(EVAL)))\n"""),
        code("""# 8. 실제 축 이름을 포함한 Chroma v2 좌표 인덱스\nrun([sys.executable, 'kosis_build_chroma_meta_index.py', '--meta-index', META, '--persist-dir', CHR, '--collection', 'kosis_meta_coordinates', '--embedding-model', 'BAAI/bge-m3', '--axis-value-limit', '300', '--prd-se-source', TABLE_CAND, '--device', 'cuda', '--reset'])\nassert (CHR / 'chroma_manifest.json').is_file()\nprint((CHR / 'chroma_manifest.json').read_text(encoding='utf-8')[:1500])\n"""),
        code("""# 9. 주기 사전 필터가 적용된 Top-5/Top-10 검색과 실제 축 우선 선택\nEVAL_V9 = MAP / 'evaluation_set_v9_enriched.csv'\nrun([sys.executable, 'enrich_mcp_gold_200_inputs.py', '--input', EVAL, '--output', EVAL_V9, '--stats', MAP / 'v9_enrichment_stats.json'])\nCAND5 = MAP / 'chroma_candidates_top5.csv'\nCAND10 = MAP / 'chroma_candidates_top10.csv'\nfor table_k, output, stats in [('5', CAND5, MAP / 'chroma_stats_top5.csv'), ('10', CAND10, MAP / 'chroma_stats_top10.csv')]:\n    run([sys.executable, 'kosis_chroma_hybrid_search.py', '--claims', EVAL_V9, '--table-candidates', TABLE_CAND, '--persist-dir', CHR, '--collection', 'kosis_meta_coordinates', '--output', output, '--stats-output', stats, '--table-top-k', table_k, '--dense-top-k', '50', '--lexical-top-k', '50', '--rerank-top-k', '60', '--final-top-k', '30', '--min-candidates-per-table', '3', '--reranker-model', 'BAAI/bge-reranker-v2-m3', '--device', 'cuda'])\nSELECT5 = MAP / 'two_stage_selected_top5.csv'\nSELECT10 = MAP / 'two_stage_selected_top10.csv'\nfor candidates, selected in [(CAND5, SELECT5), (CAND10, SELECT10)]:\n    run([sys.executable, 'select_mcp_gold_200_two_stage_coordinates.py', '--claims', EVAL_V9, '--candidates', candidates, '--output', selected, '--item-top-k', '10'])\nprint('selected =', len(csv_rows(SELECT5)), len(csv_rows(SELECT10)))\n"""),
        code("""# 10. Top-5 검증, 빈 응답 OBJ 완화, 실패 건만 Top-10 폴백\nVALID5 = MAP / 'chroma_validated_top5.csv'\nFALLBACK_IN = MAP / 'top10_fallback_input.csv'\nFALLBACK_VALID = MAP / 'top10_fallback_validated.csv'\nFINAL = MAP / 'chroma_validated_bounded_fallback.csv'\n\ndef validate_selected(selected, output):\n    run([sys.executable, 'kosis_validate_mapping_candidates.py', '--input', selected, '--meta-index', META, '--output', output, '--evaluate-all-ranks', '--strict-seeded-coordinate', '--item-top-k', '1', '--obj-top-k', '1', '--max-combinations', '1', '--allow-provisional', '--relax-empty-obj', '--max-relaxed-requests', '4', '--max-relaxed-obj-drops', '2'])\n\nvalidate_selected(SELECT5, VALID5)\nrun([sys.executable, 'kosis_topk_fallback.py', 'prepare', '--primary-validated', VALID5, '--fallback-candidates', SELECT10, '--output', FALLBACK_IN])\nif csv_rows(FALLBACK_IN):\n    validate_selected(FALLBACK_IN, FALLBACK_VALID)\nelse:\n    FALLBACK_VALID.write_text('', encoding='utf-8')\nrun([sys.executable, 'kosis_topk_fallback.py', 'merge', '--primary-validated', VALID5, '--fallback-validated', FALLBACK_VALID, '--output', FINAL])\nfinal_rows = csv_rows(FINAL)\nassert len(final_rows) == len(csv_rows(VALID5))\nassert all(r.get('mapping_status') != 'READY' for r in final_rows if r.get('obj_relaxation_used') == 'Y')\nprint('Top-10 fallback input rows =', len(csv_rows(FALLBACK_IN)))\n"""),
        code("""# 11. MCP 실제 좌표 골드 Top-k 평가와 주기 음성 골드 확인\nACTUAL_EVAL = MAP / 'actual_coordinate_eval'\nrun([sys.executable, 'evaluate_mcp_gold_200_mapping.py', '--gold', ROOT / 'data/gold/holdout8_v9_mcp_coordinate_gold.csv', '--candidates', CAND10, '--mapped', FINAL, '--ks', '1', '5', '10', '--output-dir', ACTUAL_EVAL])\ncoord_summary = json.loads((ACTUAL_EVAL / 'summary.json').read_text(encoding='utf-8'))\nnegative = csv_rows(ROOT / 'data/gold/holdout8_v9_period_negative_gold.csv')\ncandidates = csv_rows(CAND10)\ndef key(row):\n    return row.get('claim_measurement_id') or row.get('claim_id') or ''\nviolations = []\nfor gold in negative:\n    violations.extend(row for row in candidates if key(row) == gold['claim_measurement_id'] and row.get('org_id') == gold['org_id'] and row.get('tbl_id') == gold['tbl_id'])\nperiod_metrics = {'gold_rows': len(negative), 'violations': len(violations), 'filter_accuracy': (len(negative) - len({key(r) for r in violations})) / len(negative)}\n(MAP / 'period_negative_metrics.json').write_text(json.dumps(period_metrics, ensure_ascii=False, indent=2), encoding='utf-8')\nassert not violations, '주기 불일치 표가 검색 후보에 남았습니다.'\nprint(json.dumps({'coordinate': coord_summary, 'period_negative': period_metrics}, ensure_ascii=False, indent=2))\n"""),
        code("""# 12. 최종 READY 실제값 검증\nv = pd.read_csv(FINAL, dtype=str, keep_default_na=False)\nready_v = v[v['mapping_status'].eq('READY')].copy()\nready_v['_rank'] = pd.to_numeric(ready_v.get('candidate_rank', '999'), errors='coerce').fillna(999)\nready_v = ready_v.sort_values('_rank').drop_duplicates('claim_measurement_id').drop(columns='_rank')\nVERIFY_IN = MAP / 'verify_input.csv'\nVERIFIED = MAP / 'verified.csv'\nready_v.to_csv(VERIFY_IN, index=False, encoding='utf-8-sig')\nif len(ready_v):\n    run([sys.executable, 'kosis_verify_claim_values.py', '--input', VERIFY_IN, '--output', VERIFIED, '--delay', '0.12'])\n    vf = pd.read_csv(VERIFIED, dtype=str, keep_default_na=False)\n    assert not vf['verdict_code'].eq('KOSIS_API_ERROR').any()\nelse:\n    vf = pd.DataFrame()\nprint('verified READY rows =', len(vf))\n"""),
        code("""# 13. 요약과 결과 ZIP 다운로드\nfrom collections import Counter\nfinal_rows = csv_rows(FINAL)\nsummary = {\n    'articles': len(articles), 'measurements': len(measurements),\n    'evaluation_measurements': len(csv_rows(EVAL)),\n    'validated_status_rows': dict(Counter(r.get('mapping_status', '') for r in final_rows)),\n    'obj_relaxed_rows': sum(r.get('obj_relaxation_used') == 'Y' for r in final_rows),\n    'top10_fallback_attempted': sum(r.get('topk_fallback_attempted') == 'Y' for r in final_rows),\n    'top10_fallback_recovered': sum(r.get('topk_fallback_recovered') == 'Y' for r in final_rows),\n    'actual_coordinate_metrics': coord_summary, 'period_negative_metrics': period_metrics,\n    'api_error_rows': sum(r.get('mapping_status') == 'API_ERROR' for r in final_rows),\n}\n(MAP / 'gpu_run_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')\nfor src, name in [(SEM / 'manifest.json', 'semantic_manifest.json'), (CHR / 'chroma_manifest.json', 'chroma_manifest.json')]:\n    shutil.copy2(src, MAP / name)\narchive = shutil.make_archive('/content/holdout8_v9_gpu_results', 'zip', OUT)\nprint(json.dumps(summary, ensure_ascii=False, indent=2))\nprint('다운로드:', archive)\nfiles.download(archive)\n"""),
        md("""## 완료\n\n다운로드한 `holdout8_v9_gpu_results.zip`을 Codex 작업에 첨부하세요. 대용량 Chroma 인덱스는 결과 ZIP에 포함하지 않습니다.\n"""),
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


def build_bundle() -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    archive_files: dict[str, Path] = {path.name: path for path in ROOT.glob("*.py")}
    for relative in (
        "requirements.txt", "requirements-ml.txt",
        "data/holdout8_stratified_articles.csv",
        "data/holdout8_stratified_assignments.csv",
        "data/holdout8_stratified_manifest.json",
        "data/seed_region_codes.csv",
        "data/reference/kosis_table_summary.csv",
        "data/gold/holdout8_v9_mcp_coordinate_audit.jsonl",
        "data/gold/holdout8_v9_mcp_coordinate_gold.csv",
        "data/gold/holdout8_v9_mcp_coordinate_gold.manifest.json",
        "data/gold/holdout8_v9_period_negative_gold.csv",
        "docs/holdout8_v9_prereg_20260810.md",
    ):
        archive_files[relative] = ROOT / relative
    for name in ("01_sentences.csv", "03_claim_contexts.csv", "05_hcx_measurements.csv"):
        archive_files[f"data/checkpoints/{name}"] = CHECKPOINTS / name
    missing = [path for path in archive_files.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"bundle files missing: {missing}")
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "purpose": "holdout8 v9 actual-axis, periodicity, OBJ relaxation, bounded Top-10 fallback",
        "secrets_included": False,
        "gold_included": True,
        "gold_rows": 4,
        "files": {name: sha256(path) for name, path in archive_files.items()},
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
    manifest = build_bundle()
    print(f"notebook={NOTEBOOK}")
    print(f"bundle={BUNDLE}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
