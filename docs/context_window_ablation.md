# 이전 문맥 1~5문장 비교 실험

## 목적

같은 Top50 기사와 같은 claim span에서 HCX에 제공하는 이전 문장 수만
1, 2, 3, 4, 5로 바꿔 `in_ready` 성능을 비교한다. 문장 분리와 claim span
탐지를 매번 다시 실행하면 비교 대상 자체가 달라지므로, 두 단계의 출력은
반드시 고정한다.

## 공통 골드

- 파일: `data/gold/context_top50_common_gold_v1.csv`
- 후보: 797건
- `gold_ready=Y`: 92건
- `gold_ready=N`: 705건
- 판정: 수치·단위·기간·주기·역할이 문맥에 맞고 KOSIS 공식 통계표에 직접
  대응할 때만 Y

이 골드는 Codex가 동일 규칙으로 판정한 프로젝트용 v1이다. 새 실험에서
기존 797개에 없는 READY 후보가 나오면 `context_window_unseen_ready.csv`에
모아 같은 기준으로 추가 판정한다.

## 통제 조건

모든 방법에서 다음 설정을 고정한다.

- sentence CSV와 claim span CSV
- 제목, 발행일, 첫 3문장 공통 문맥
- 이후 문장 0개
- 기사 내 관련 문장 자동 추가 0개
- BGE-M3 Top-20, reranker Top-20, HCX 참고 후보 Top-5
- HCX-007 프롬프트와 `prepare_kosis_mapping_input.py` 게이트

변경하는 값은 `previous_window` 하나뿐이다.

## 실행

기존 Top50 실행 폴더의 고정 파일을 사용한다.

```bash
python run_context_window_ablation.py \
  --sentences /content/drive/MyDrive/NLP_05-Team-Project-3/runs/contextual_top50_context_v2_8x3/01_sentences.csv \
  --spans /content/drive/MyDrive/NLP_05-Team-Project-3/runs/contextual_top50_context_v2_8x3/03_claim_spans.csv \
  --semantic-index /content/drive/MyDrive/NLP_05-Team-Project-3/indexes/kosis_bge_m3 \
  --out-dir /content/drive/MyDrive/NLP_05-Team-Project-3/runs/context_window_ablation_v1 \
  --windows 1 2 3 4 5 \
  --next-window 0 \
  --related-limit 0 \
  --lead-sentences 3 \
  --device cuda
```

중단 후 같은 명령을 다시 실행하면 BGE와 HCX 단계는 완료된 claim부터
이어받는다. 설정을 바꿔 처음부터 다시 만들 때만 `--overwrite`를 사용한다.

각 방법의 완전한 비교 파일은 다음 경로에 생성된다.

```text
context_window_ablation_v1/prev_1/06_in_ready_all.csv
context_window_ablation_v1/prev_2/06_in_ready_all.csv
context_window_ablation_v1/prev_3/06_in_ready_all.csv
context_window_ablation_v1/prev_4/06_in_ready_all.csv
context_window_ablation_v1/prev_5/06_in_ready_all.csv
```

## 평가

```bash
python evaluate_context_window_ablation.py \
  --gold data/gold/context_top50_common_gold_v1.csv \
  --run prev_1=/content/drive/MyDrive/NLP_05-Team-Project-3/runs/context_window_ablation_v1/prev_1/06_in_ready_all.csv \
  --run prev_2=/content/drive/MyDrive/NLP_05-Team-Project-3/runs/context_window_ablation_v1/prev_2/06_in_ready_all.csv \
  --run prev_3=/content/drive/MyDrive/NLP_05-Team-Project-3/runs/context_window_ablation_v1/prev_3/06_in_ready_all.csv \
  --run prev_4=/content/drive/MyDrive/NLP_05-Team-Project-3/runs/context_window_ablation_v1/prev_4/06_in_ready_all.csv \
  --run prev_5=/content/drive/MyDrive/NLP_05-Team-Project-3/runs/context_window_ablation_v1/prev_5/06_in_ready_all.csv \
  --out-dir /content/drive/MyDrive/NLP_05-Team-Project-3/runs/context_window_ablation_v1/evaluation
```

선택 기준은 F1을 1순위로 두고 precision, recall, READY 수, 실행 시간과 API
비용을 함께 본다. Accuracy는 N이 많은 불균형 데이터에서 높게 보일 수
있으므로 단독 선택 기준으로 사용하지 않는다.
