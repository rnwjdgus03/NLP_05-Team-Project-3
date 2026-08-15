# 잠금 홀드아웃 300 v10-sqlite 사전등록

## 목적

잠금 기사 300건에서 좌표 Chroma를 사용하지 않고 `표 검색 → SQLite exact resolver → KOSIS API` 구조의 골드 비공개 예측을 고정한다.

## 입력 잠금

- 기사: `data/locked_holdout_300_articles.csv`
- 기사 수와 고유 URL: 각각 300
- 잠금 상태: `LOCKED_DO_NOT_TUNE`
- 라벨 상태: `UNSEEN_LOCKED_INPUT_NOT_YET_MCP_GOLD`
- 기존 gold250·holdout5~8 URL 중복: 0

## 동결 구조

```text
HCX-007 structured measurements
→ lexical + BGE-M3 + reranker table Top-10
→ Top-10 table metadata import into SQLite
→ SQLite ITEM Top-5 + typed OBJ exact resolution
→ one seeded coordinate per measurement
→ KOSIS Open API validation
→ value verification
→ gold-blind prediction freeze
```

## 고정 설정

- 표 임베딩 모델: `BAAI/bge-m3`
- 임베딩 차원: 1024
- 리랭커: `BAAI/bge-reranker-v2-m3`
- 표 후보: Top-10
- 메타 수집 표: Top-10
- SQLite ITEM 후보: Top-5
- 좌표 Chroma: 사용하지 않음
- OBJ target 미일치 좌표 자동 READY: 금지
- API 요청 좌표: SQLite가 선택한 단일 seeded coordinate

## 평가 누수 방지

1. 실제 KOSIS 좌표 골드는 번들에 포함하지 않는다.
2. 먼저 `locked_holdout_300_predictions.csv`와 SHA-256을 고정한다.
3. 예측 해시가 고정된 뒤 KOSIS MCP 실제 골드를 별도로 생성한다.
4. v10 실행 중 발견한 실패를 보고 코드·가중치·alias를 수정하지 않는다.
5. v8·v9 개발 결과는 참고만 하고 잠금 300의 정답으로 사용하지 않는다.

## 산출물

- `locked_holdout_300_predictions.csv`
- `locked_holdout_300_article_predictions.csv`
- `locked_holdout_300_prediction_manifest.json`
- `07_mapping_sqlite/sqlite_exact/` 단계별 CSV
- `gpu_run_summary.json`

## 승격 기준

정답 골드 생성 후 표 Recall@1/5/10, ITEM exact, typed OBJ exact, 기간 exact, full-coordinate exact, READY precision·coverage, verdict accuracy를 분리 평가한다.

v10은 자동으로 새 기준선이 되지 않으며, 사전등록 지표에서 기존 기준선보다 개선될 때만 승격한다.
