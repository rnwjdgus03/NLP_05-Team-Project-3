# 홀드아웃7 v4 블라인드 결과

## 결과 출처

- 결과 ZIP: `holdout7_v4_gpu_results.zip`
- 가져온 ZIP SHA-256: `33322a1ed6b21af498a1367177891151cbb8d5c42ecde37b5d670d0dd84b92f3`
- 입력: 개발 골드 및 홀드아웃5·6과 URL이 겹치지 않는 기사 50건
- 판정: `REVIEW / INCONCLUSIVE`

## 실행 완결성

| 단계 | 건수 |
|---|---:|
| 기사 | 50 |
| 문장 | 960 |
| claim context | 223 |
| HCX measurement | 243 |
| 잠금된 평가 measurement | 42 |
| 평가에 남은 기사 | 9 |
| Top-5 선택 성공 | 41/42 |
| Top-10 선택 성공 | 41/42 |
| KOSIS 실제값 검증 성공 | 0/42 |
| KOSIS API 오류 | 0 |

API 장애는 없었지만 유효한 KOSIS 좌표와 실제값을 확정한 행이 없었다.
따라서 이 실행은 검색 규칙의 안정성은 볼 수 있지만 정확도나 일반화 성능을
측정하는 홀드아웃 평가는 아니다.

## Top-5 / Top-10 블라인드 비교

- 공통 선택: 41건
- 동일한 ITEM/OBJ 좌표 선택: 41/41, 100%
- 직접 target match 표시: Top-5 25건, Top-10 25건
- 추가로 매핑된 Top-10 행: 0건

Top-10을 사용해도 선택이 흔들리지 않았다는 점은 안정성 신호다. 그러나 정답
좌표나 실제값이 없으므로 100% 일치는 품질 향상이 아니라 두 설정이 같은 결과를
냈다는 뜻으로만 해석해야 한다.

## 실제값 검증 실패 분해

| 버킷 | 건수 |
|---|---:|
| `COORDINATE_RETURNS_NOTHING` | 19 |
| `CANDIDATE_NOT_DECISIVE` | 8 |
| `UNIT_UNVERIFIABLE` | 6 |
| `NO_DATA_AT_COORDINATE` | 6 |
| `COORDINATE_NOT_FOUND` | 3 |

후보 검증 파일에는 후보 410행이 있으며 `MAPPING_FAILED` 328행,
`NEEDS_CONFIRMATION` 82행이다. `READY` 또는 검증된 행은 없다. 회사 매출,
회사채 만기 금액처럼 KOSIS 공식 통계가 아닌 문장이 KOSIS 평가 대상으로 남은
사례도 확인되어 KOSIS-ready 게이트의 정밀도가 부족하다.

## 구조화 OBJ 규칙 검증 가능성

42개 잠금 measurement에서 추출된 구조화 대상 수는 다음과 같다.

| 대상 축 | 건수 |
|---|---:|
| 출발 국가 | 0 |
| 도착 국가 | 0 |
| 지역 | 0 |
| 연령 | 1 |
| 성별 | 0 |
| 품목 | 0 |

따라서 이번 무작위 홀드아웃은 국가·연령·성별·품목을 OBJ에 직접 연결하는 v4
규칙을 검증할 표본 구성이 아니다. `two_stage_obj_target_terms` 41건은 대부분
ITEM/indicator fallback으로 만들어진 값이므로 구조화 OBJ target 41건으로
해석하면 안 된다.

## 결론과 다음 조치

1. 개발 골드 A/B의 근거로 표 후보 풀은 `table_top_k=10`을 유지한다.
2. 현재 홀드아웃 결과는 안정성 검사는 통과했지만 정확도 검사는 미완료로 둔다.
3. 회사·정책·금융상품 고유 수치를 제외하도록 KOSIS-ready 게이트를 강화한다.
4. 국가·연령·성별·품목 대상이 포함되도록 별도의 층화 홀드아웃을 잠근다.
5. 남은 행은 KOSIS MCP 실제 조회나 사후 자동 골드 생성으로 ITEM/OBJ 정답을
   붙인 뒤 Top-5/Top-10 정확도를 다시 계산한다.
