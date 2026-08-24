# v26 Structured Recall

## 상태

v26은 구현·문법 검사·로컬 전처리 회귀까지 완료됐지만, 아직 서비스 후보로
동결하지 않았다. 공개된 v25 블라인드 30건은 실패 원인 진단 이후 개발셋으로
전환했으며, v26 선택에는 다음 신규 블라인드 골드를 사용하지 않는다.

## 변경점

1. Excel serial 기사 날짜를 실제 날짜로 복원한다.
2. `지난해`, `작년 N분기`, `전달보다`, `전년 동기 대비 감소 폭`처럼 기사에
   명시된 근거만 사용해 기간·주기·변화량 계약을 복구한다.
3. Stage A에 공식 PostgreSQL ITEM 및 OBJ 이름의 구조 검색 채널을 추가한다.
4. 의미 reranker 이후에도 공식 component literal hit를 Top-10의 제한된 tail에
   보존한다.
5. Stage B에서 명시 대상 OBJ와 나머지 축의 단일 공식 집계값으로 결정 가능한
   좌표를 beam 밖에서 생성한다.
6. Stage C에서 명시 대상이 있는데 정확 좌표가 없으면 후보를 내지 않는다.
   이 경우 최종 상태는 강제 판정이 아니라 `UNRESOLVED`여야 한다.

## 검증 규칙

- v25 동결본은 수정하지 않는다.
- 공개된 v25 골드는 개발 회귀에만 사용한다.
- v26 코드 선택을 끝낸 뒤 코드·입력·인덱스 SHA를 고정한다.
- 그 후 완전 미사용 기사에서 실제 KOSIS API 좌표 골드를 만들고 한 번만
  블라인드 평가한다.
- 서비스 연결 기준은 Stage A 표 Top-10 80%, 표+ITEM Top-5 70%, ITEM+OBJ
  Top-5 60%, Full Top-5 50%, 잘못된 VALUE_MISMATCH 0건에 가깝게 유지다.

## 실행

서버 재시작 후 `app_v26`에 이 디렉터리를 배포하고 다음을 실행한다.

```bash
cd /home/ubuntu/kosis-project/app_v26
chmod +x run_v26_opened_diagnostic.sh
tmux new-session -d -s kosis-v26 \
  'bash run_v26_opened_diagnostic.sh 2>&1 | tee /home/ubuntu/kosis-project/runs/v26_structured_recall_opened_v25_dev_20260820/pipeline.log'
```
