# 홀드아웃8 v5 실행 전 점검

- Colab notebook: `notebooks/holdout8_stratified48_v5_gpu_colab.ipynb`
- Colab input bundle: `outputs/holdout8_stratified48_v5/holdout8_v5_colab_input_bundle.zip`
- Bundle SHA-256: `3539ca467221334a5ebb65f6cae8b788521cb7b47438e16f01ef6cc8877fd75c`
- Expected result: `holdout8_v5_gpu_results.zip`

## 층화 잠금

- 총 48개 기사
- 국가 12 / 연령 12 / 성별 12 / 품목 12
- 기존 골드·홀드아웃 URL 중복 0
- 기사 입력 SHA-256: `745bf829ec0a961ebdb1249c99fb3727fc9db45c0aba7ea8bfcca7459ab076d6`

## KOSIS-ready 게이트 재생 결과

- 홀드아웃7 measurement 475건: READY 27 / ENRICH 143 / REJECT 305
- REJECT와 ENRICH를 합친 비-READY: 448
- 금융상품 수치 제외: 15
- 개별기업 수치 제외: 5
- READY의 회사채·기업어음·연결 기준 매출·영업이익 패턴 잔존: 0

## 실제 KOSIS MCP smoke evaluation

- 대상: 2024년 국민 1인당 쌀 소비량 55.8kg
- 실제 좌표: `101 / DT_1ED0001 / ITEM T10(전가구) / OBJ1 10(쌀) / OBJ2 00(계)`
- Top-5와 Top-10 표 recall: 각각 100%
- Top-5와 Top-10 ITEM accuracy: 각각 0%
- Top-5와 Top-10 full mapping accuracy: 각각 0%
- 발견 오류: 좌표 검색이 실제 `전가구(T10)` 대신 `비농가(T30)`를 선택함

## 다음 단계

1. Colab에서 notebook을 열고 GPU 런타임을 선택한다.
2. input bundle ZIP 하나를 업로드하고 셀을 위에서 아래로 실행한다.
3. 마지막 셀에서 받은 `holdout8_v5_gpu_results.zip`을 Codex 작업에 첨부한다.
4. 결과 ZIP의 measurement를 KOSIS MCP search → validate → get_data로 조회해 자동 골드를 만든다.
5. MCP 확인 성공 행만 분모로 삼아 Top-5와 Top-10의 표·ITEM·OBJ·기간·전체 좌표 정확도를 재평가한다.
