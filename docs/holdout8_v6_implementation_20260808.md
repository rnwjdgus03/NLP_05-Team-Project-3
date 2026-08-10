# holdout8 v6 구현 및 로컬 재생 결과

## 반영 사항

1. KOSIS 표 검색 쿼리에 기사에 명시된 조사명과 국가·지역·연령·성별·품목 대상 축을 추가했다.
2. `rate_change`를 `DERIVED_VALUE_REQUIRES_COMPUTATION`으로 분류해 직접 공표 ITEM 확인 또는 수준값 재계산 전에는 READY에 들어가지 않게 했다.
3. ISO 날짜와 Excel 일련번호 날짜를 모두 해석하고 상대 월의 대상 기간과 비교 기간을 분리했다.
4. 좌표 재순위에서 최초 표 고정을 제거하고 ITEM 일치, OBJ 대상 일치 수, 기존 검색 점수 순으로 전체 후보를 선택하게 했다.
5. Colab v6에서는 Top-5/Top-10 선택 결과를 각각 KOSIS API 좌표 검증에 연결한다.

## holdout8 v5 산출물 로컬 재생

- HCX measurement: 791
- v5 READY: 135
- v6 READY: 93
- 기존 READY 중 파생 증감률로 ENRICH 이동: 42
- 전체 입력에서 `DERIVED_VALUE_REQUIRES_COMPUTATION`: 49
- Excel 일련번호 기사 135행 중 상대기간 복구: 40
- 예시: `작년 12월` → 대상 `202412`, 비교 `202312`
- 예시: `지난 2월 … 지난해 같은 달` → 대상 `202502`, 비교 `202402`
- 기존 v5 좌표 후보 재순위: 135행 선택, 최초 표 변경 23행, ITEM 명시 일치 55행, OBJ 전체 일치 77행, OBJ 일부 이상 일치 106행
- 기존 v5 후보 + MCP 실제 골드 9행 재생: 최종 표 일치 2/9, ITEM 일치 0/9

마지막 수치는 새 조사명·대상축 BGE 검색을 다시 실행하기 전의 기존 v5 후보 재생 결과다. 따라서 v6 최종 Top-5/Top-10 성능은 Colab GPU 결과로 별도 판정한다.

## 검증

- 변경 Python 파일 `py_compile` 통과
- pytest 미설치 환경에서 fixture 없는 관련 테스트 49개 직접 실행 통과
- v6 notebook JSON 및 ZIP manifest 내부 SHA-256 검증 통과

## Colab 입력

- Notebook: `notebooks/holdout8_stratified48_v6_gpu_colab.ipynb`
- Bundle: `outputs/holdout8_stratified48_v6/holdout8_v6_colab_input_bundle.zip`
- Bundle SHA-256: `13964ea76f2aca8d8b7922867fd39c61131a06b9db25a6c3404bab69dcf5b1c2`
