# 잠금 홀드아웃 300 v9 사전등록

## 목적

새 기사 300건에서 현재 v9 파이프라인의 일반화 성능을 정답 비공개 상태로 측정한다.

## 잠금 입력

- 기사 파일: `data/locked_holdout_300_articles.csv`
- 기사 수와 고유 URL 수: 각각 300
- 기존 gold250 및 holdout5~8 URL 중복: 0
- 잠금 상태: `LOCKED_DO_NOT_TUNE`
- 선정 seed: `locked-holdout-300-articles-v1-20260810`

## 동결 파이프라인

- HCX 모델: `HCX-007`
- 표 임베딩: `BAAI/bge-m3`, 1024차원
- 표 검색: lexical + BGE-M3 + BGE reranker
- 좌표 검색: ITEM과 OBJ를 분리 평가하는 2단계 선택
- 상위 표: Top-5 우선, 기술적 실패 건만 Top-10 폴백
- 안전 규칙: OBJ 완전 일치 전 READY 금지, OBJ 완화 결과 READY 금지
- 주기 규칙: 월·분기·연 주기 불일치 표를 검색 전에 제외

## 평가 누수 방지

1. 이 문서와 freeze manifest를 만든 뒤 코드·설정·입력 해시를 변경하지 않는다.
2. 300건 예측 파일을 먼저 생성하고 `gold_accessed=N`으로 고정한다.
3. KOSIS MCP 실제 좌표·값 골드는 예측 파일 해시가 확정된 뒤 별도로 만든다.
4. 골드 생성 중 발견한 실패 사례로 현재 실행을 수정하거나 재실행하지 않는다.
5. 수정이 필요하면 잠금 300을 폐기하고 새로운 기사 홀드아웃을 만든다.

## 고정 산출물

- `locked_holdout_300_predictions.csv`
- `locked_holdout_300_article_predictions.csv`
- `locked_holdout_300_prediction_manifest.json`
- 원시 단계별 체크포인트와 `gpu_run_summary.json`

## 후속 평가

- 표 Recall@1/5/10
- ITEM 정확도와 OBJ 완전 일치율
- 기간·주기 정확도
- 실제값 일치율
- READY 정밀도·재현율·F1
- 잘못된 READY 비율과 기사 단위 부트스트랩 신뢰구간
