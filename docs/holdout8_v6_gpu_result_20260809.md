# 홀드아웃8 v6 GPU 결과 감사

## 결론

- v6 실행은 정상 완료됐고 KOSIS API 오류는 0건이다.
- MCP 실제 골드 9건에서 표 Recall@5/10은 22.22%(2/9)로 v5와 같았다.
- 고유 measurement 키로 평가기를 수정한 뒤 최종 표 정확도는 v5 0%에서 v6 22.22%(2/9)로 개선됐다.
- v6 ITEM 정확도와 전체 좌표 정확도는 0%였다.
- Top-5와 Top-10은 97건 모두 동일했다. 원인은 1차 표 검색이 기본값 5개만 저장해 Top-10 arm에도 동일한 후보가 공급된 설정 오류다.

## 입력 무결성

- 사용자 ZIP: `holdout8_v6_gpu_results.zip`
- SHA-256: `3d78aa0b4ca561256099458a7ab30bb0af2eb3305b005a29ee5ad078cd645d19`
- ZIP 크기: 1,295,178 bytes
- 압축 파일: 36개
- 해제 파일 총 크기: 13,777,852 bytes
- API 오류: 0건

## 파이프라인 산출량

| 단계 | v5 | v6 | 변화 |
|---|---:|---:|---:|
| 기사 | 48 | 48 | 0 |
| 문장 | 1,054 | 1,054 | 0 |
| claim context | 324 | 317 | -7 |
| HCX measurement | 791 | 769 | -22 |
| KOSIS READY | 135 | 97 | -38 |
| KOSIS ENRICH | 336 | 360 | +24 |
| KOSIS REJECT | 320 | 312 | -8 |

HCX 추출은 비결정적이므로 measurement 수 변화 전체를 게이트 효과로 해석하면 안 된다.

## 게이트 및 층화

- `DERIVED_VALUE_REQUIRES_COMPUTATION`: 49건(ENRICH 47, REJECT 2)
- READY 97건에는 `rate_change`가 0건이다.
- READY 의미형: amount 32, count 57, multiple 1, rate_level 7
- 회사채·은행채·기업어음·개별 회사 매출/영업이익 패턴 READY: 0건

| 층 | READY measurement | READY 기사 |
|---|---:|---:|
| 국가 | 2 | 2 |
| 연령 | 23 | 4 |
| 성별 | 63 | 8 |
| 품목 | 9 | 2 |

파생률 제외는 작동했지만 최종 평가 분모는 여전히 성별 층에 크게 치우쳤다.

## v6 MCP 실제 골드 평가

| 지표 | Top-5 | Top-10 | v5 |
|---|---:|---:|---:|
| Mapping coverage | 100.00% | 100.00% | 100.00% |
| Table Recall | 22.22% | 22.22% | 22.22% |
| Final table accuracy | 22.22% | 22.22% | 0.00% |
| ITEM accuracy | 0.00% | 0.00% | 0.00% |
| Period accuracy | 55.56% | 55.56% | 55.56% |
| Full-coordinate accuracy | 0.00% | 0.00% | 0.00% |

기존 평가기는 `claim_id`를 `claim_measurement_id`보다 먼저 사용해 한 claim 안의 다른 measurement를 채점했다. 이를 고친 뒤 임금 2건의 정답 표 선택이 확인됐다.

## 좌표 검증 결과

- 검증 입력 97건: READY 5, NEEDS_CONFIRMATION 18, MAPPING_FAILED 74
- 실제값 조회 5건: 일치 1, 판단불가 2, 불일치 2
- READY 5건은 모두 비정규직/임금 계열로, 도메인 커버리지가 좁다.
- 임금 정답 표 2건은 선택했지만 ITEM을 `증감(전년동월)`이 아니라 `월평균임금`으로 골랐다.
- `정규직`이 `-비정규직`에 부분 문자열로 일치했고, `-` 값들이 OBJ target으로 기록돼 OBJ 일치 수가 부풀려졌다.

## 사후 수정 재생

동일 v6 GPU 후보에 아래 수정만 적용해 재생했다.

1. 증감값은 직접 ITEM `증감(전년동월)`을 우선한다.
2. `-`는 OBJ target에서 제외한다.
3. `정규직`과 `비정규직`을 분리한다.
4. 기존 `measurement_role`·`value_type`을 enrichment가 덮어쓰지 않는다.
5. 조사월+측정연도를 결합하고 연간 대상 표현을 보존한다.
6. 골드에 비교기간이 N/A이면 보존된 문맥 비교기간을 감점하지 않는다.

사후 재생 결과는 표 정확도 22.22%, ITEM 정확도 22.22%, 기간 정확도 66.67%, 전체 좌표 정확도 22.22%(2/9)다.

## 다음 실행

v7은 v6 HCX measurement를 고정 재사용하고 1차 표 후보와 KOSIS 메타를 모두 10위까지 확장한다. 따라서 HCX API는 다시 호출하지 않으며 Top-5/Top-10이 처음으로 서로 다른 후보 풀을 평가한다.
