# 실행 가이드

아래 명령은 저장소 루트에서 실행한다. 입력·인덱스·DB는 Git에 포함되지 않는다.

## 1. 환경

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

`.env`에 필요한 키와 DSN을 입력한다.

```text
CLOVA_API_KEY=...
KOSIS_API_KEY=...
KOSIS_POSTGRES_DSN=postgresql:///kosis_project
```

## 2. 기사에서 1차 게이트까지

문맥 보존형 전체 앞단:

```powershell
python run_contextual_news_kosis_pipeline.py `
  --articles data\raw\news_articles.csv `
  --table-index data\reference\kosis_table_summary.csv `
  --semantic-index data\indexes\kosis_bge_m3 `
  --out-dir outputs\contextual_v24 `
  --device cuda `
  --stop-after gate
```

이미 HCX measurement CSV가 있으면 게이트만 다시 실행한다.

```powershell
python prepare_kosis_mapping_input.py `
  --input outputs\contextual_v24\05_hcx_measurements.csv `
  --output outputs\contextual_v24\06_mapping_ready.csv `
  --enrich-output outputs\contextual_v24\06_mapping_enrich.csv `
  --rejected-output outputs\contextual_v24\06_mapping_reject.csv `
  --all-output outputs\contextual_v24\06_in_ready_all.csv
```

고정 회귀셋에서는 예상 READY 수가 변하면 중단하도록 `--expect-ready <N>`을 추가한다.

## 3. BGE-M3 표 인덱스

```powershell
python kosis_build_embedding_index.py `
  --table-index data\reference\kosis_table_summary.csv `
  --out-dir data\indexes\kosis_bge_m3 `
  --device cuda
```

CPU도 가능하지만 전체 카탈로그 임베딩과 rerank는 오래 걸린다. Colab GPU에서는 `--device cuda`를 사용하고 생성된 인덱스를 별도 보관한다.

## 4. v24 좌표 검색

Stage A — 표 후보 검색:

```powershell
python run_kosis_coordinate_stage_a.py `
  --claims outputs\contextual_v24\06_mapping_ready.csv `
  --semantic-index data\indexes\kosis_bge_m3 `
  --postgres-dsn $env:KOSIS_POSTGRES_DSN `
  --output outputs\coordinate_v24\stage_a_tables.jsonl `
  --device cuda
```

Stage B — ITEM/OBJ 좌표 beam 생성:

```powershell
python run_kosis_coordinate_stage_b.py `
  --table-pool outputs\coordinate_v24\stage_a_tables.jsonl `
  --postgres-dsn $env:KOSIS_POSTGRES_DSN `
  --output outputs\coordinate_v24\stage_b_beam.jsonl `
  --preserve-table-fallback `
  --device cuda
```

Stage C — 좌표 rerank:

```powershell
python run_kosis_coordinate_stage_c.py `
  --beam-pool outputs\coordinate_v24\stage_b_beam.jsonl `
  --output outputs\coordinate_v24\stage_c_top3.jsonl `
  --fallback-output outputs\coordinate_v24\stage_c_top5_review.jsonl `
  --device cuda
```

각 단계는 JSONL checkpoint를 읽어 완료된 claim을 건너뛴다. 동일 출력으로 재실행해 이어갈 수 있지만 입력 fingerprint나 PostgreSQL snapshot이 바뀌면 새 실행 디렉터리를 사용한다.

## 5. 실제값 검증

```powershell
python run_kosis_top5_verification.py `
  --claims outputs\contextual_v24\06_mapping_ready.csv `
  --candidates outputs\coordinate_v24\stage_c_top5_review.jsonl `
  --output outputs\coordinate_v24\verified_candidates.jsonl `
  --claim-output outputs\coordinate_v24\verified_claims.jsonl `
  --postgres-dsn $env:KOSIS_POSTGRES_DSN `
  --sqlite-cache outputs\coordinate_v24\kosis_api_cache.sqlite
```

실제 API 호출에는 `KOSIS_API_KEY`가 필요하다. 메타데이터·기간·단위가 불충분한 후보는 억지로 확정하지 않고 `UNRESOLVED`로 남긴다.

## 6. 평가와 테스트

좌표 Top-k 평가:

```powershell
python evaluate_coordinate_topk.py --help
```

회귀 테스트:

```powershell
python -m pytest -q
```

블라인드 31건은 이미 v24b에 대해 한 번 사용한 감사셋이다. `evaluation/blind_v24b/`의 스크립트는 재현과 감사용이며 새 규칙 튜닝용이 아니다.
