# B팀 KOSIS 2,001건 검증·골드셋·독립 홀드아웃 평가 보고

## 결론

- 원격의 2,001건 자동 실행 결과는 최종 사실판정이 아닌 단위/시점/증감률 오류 진단 자료로 사용했다.
- 24건 표본의 의미 매핑 품질 게이트가 실패해 1,998건 전체를 새 로직으로 재실행하지 않았다.
- 기존 자동 일치 70건을 다시 감사해 미래시점·전망문장·수동확인 후보로 재분류했다.
- 70건 정확시점 재실행 자동 판정: 일치 35건, 불일치 26건, 판단불가 9건.
- 일치 후보 33건을 수동 대조해 15건을 우선 확정하고 8건을 재매핑 대상으로 분리했다.
- 재매핑 8건 중 6건을 추가 확정해 최종 일치 21건을 확보했다.
- 동남아 수출 1건은 KOSIS 지역 집계코드가 없고, 가공식품 기여도 1건은 KOSIS에 기여도 자료가 없어 판단불가로 분리했다.
- 나머지는 뉴스가 틀렸다는 뜻이 아니라, 표/항목/시점/단위 기준 재검토가 필요한 건으로 분리했다.
- 이후 100건 개발용 골드셋으로 현재 시스템 성능을 측정하고, 반복 지표 코드북을 만든 뒤 재검토 1,643건 전체를 9개 배치로 확대 처리했다.
- 확대 과정에서는 숫자만 맞는 오판을 막기 위해 단일 지표·단일 시점·전국 총계 또는 확정 세부지표가 모두 명확한 경우만 자동조회 후보로 인정했다.
- 개발용 골드와 주장·기사 중복이 없는 독립 홀드아웃 100건에서 동결 코드북을 평가했다. 자동 결정한 범위의 정확도는 96.2%였지만 커버리지가 26.0%에 그쳐 항목·시점 엄격 정확도는 18.2%로 80% 게이트에 실패했다.
- 따라서 현재 1,281건의 자동 확정 확대는 보류하고, 오류 분석 결과를 코드북 v2 개발 자료로 전환한다.

## 100건 골드셋 평가

| 항목 | 결과 | 해석 |
| --- | ---: | --- |
| 표본 구성 | 100건 | 물가·고용·무역·인구·소매 각 20건, 정확시점 불일치 22건 포함 |
| KOSIS 직접 검증 가능 | 51건 | 사람이 통계표·항목·시점을 확정할 수 있는 주장 |
| KOSIS 직접 검증 불가 | 49건 | KOSIS 미제공 26, 정보 부족 7, 기여도 미제공 2, 지역·분류 불일치 14 |
| 검증 가능 여부 정확도 | 61.0% | 기존 시스템의 직접 검증 가능/불가 분류 |
| 통계표 매핑 정확도 | 60.8% | 직접 검증 가능 51건 기준 |
| 항목 매핑 정확도 | 47.1% | obj_l1·obj_l2·itm_id 기준 |
| 시점 매핑 정확도 | 58.8% | 주기와 목표 시점 기준 |
| 항목·시점 결합 정확도 | 41.2% | 의미 매핑의 핵심 품질 지표 |
| 기존 API 기술 성공률 | 94.1% | 값 수신 성공이며 의미 정확도와는 다름 |
| 기존 최종 판정 일치율 | 43.0% | 골드 판정과 기존 판정 비교 |
| 수동 확정 코드북 API 성공률 | 100.0% | 51/51, 개발용 골드셋의 확정 매핑 재조회 결과 |

골드 최종 판정은 일치 45건, 불일치 6건, 판단불가 49건이다. 수동 확정 코드북의 100%는 자동 시스템의 독립 정확도가 아니므로 별도 홀드아웃 평가가 필요하다.

## 독립 홀드아웃 100건 평가

| 항목 | 결과 | 해석 |
| --- | ---: | --- |
| 표본 구성 | 100건 | 개발용 골드와 claim/article 중복 0, 5개 분야 각 20건 |
| 골드 검증 가능 | 33건 | 사람이 통계표·항목·시점을 확정한 주장 |
| 골드 검증 불가 | 67건 | KOSIS 미제공 35, 정보 부족 24, 지역·분류 불일치 8 |
| 자동 결정 커버리지 | 26.0% | 검증가능 또는 검증불가를 자동 결정한 26/100 |
| 자동 결정 구간 정확도 | 96.2% | 자동 결정한 26건 중 25건 정답 |
| 자동 검증가능 매핑 정밀도 | 100.0% | 통계표·항목·시점이 맞은 6/6 |
| 항목·시점 결합 엄격 정확도 | 18.2% | 검증 가능 33건 전체 분모, 보류는 오답 |
| 자동매핑 API 성공률 | 66.7% | 자동 검증가능 6건 중 값 조회 4건 |
| 골드 API 성공률 | 87.9% | 수동 확정 33건 중 값 조회 29건 |
| 80% 품질 게이트 | 실패 | 1,281건 자동 확정 확대 보류 |

결과는 “자동 판단이 무의미하다”가 아니라 “판단한 범위의 정밀도는 높지만 코드북 범위가 좁다”는 뜻이다. 검증 가능 보류 26건, 검증 불가 보류 48건, 과배제 1건(`C20191`)을 코드북 v2 개선 대상으로 기록했다. 현재 홀드아웃을 이용해 규칙을 수정한 뒤 같은 점수를 독립 성능으로 다시 보고하지 않고, 새 표본에서 재평가한다.

## 1,643건 확대 결과

| 구분 | 건수 | 의미 |
| --- | ---: | --- |
| 자동조회 후보 | 33 | 엄격한 코드북·문맥 규칙 통과 |
| API 판정 완료 | 30 | 일치 28, 불일치 2 |
| 목표 시점 값 미제공 | 3 | 최신 출생 통계로 재검토 유지 |
| 수동검토 유지 | 1,281 | 세부 분류·대상 숫자·시점 문맥 추가 확인 필요 |
| 비검증 사유 분류 | 329 | 정보 부족 187, KOSIS 미제공 120, 기여도 미제공 22 |

기존 판단불가 337건은 KOSIS 미제공 273건, 정보 부족 32건, 지역·분류 불일치 31건, 기여도 미제공 1건으로 분리했다.

## v6 기준 기존 2,001건 상태

| 구분 | 건수 | 의미 |
| --- | ---: | --- |
| 재검토필요_증감률불일치 | 858 | 증감률 claim과 KOSIS 계산값이 다름. 항목/시점/전년대비 기준 재확인 필요 |
| 재검토필요_수준값불일치 | 763 | 수준값 claim과 KOSIS 값이 다름. 단위/항목/표 매칭 재확인 필요 |
| 판단불가_API조회실패 | 184 | API 응답 없음 또는 값 조회 실패 |
| 판단불가_증감계산값없음 | 123 | 증감률 claim인데 이전 시점 값이 없어 계산 보류 |
| 검증완료_수동확정일치 | 15 | 표/항목/단위/시점과 KOSIS 실제값을 수동 대조해 확정 |
| 검증완료_재매핑확정일치 | 6 | 세부 품목·연령·시점으로 재매핑한 뒤 실제값 재검증 완료 |
| 판단불가_KOSIS직접검증불가 | 10 | 해외지표·전망·모형결과·비지원 주기로 KOSIS 직접검증 불가 |
| 판단불가_KOSIS지역집계없음 | 1 | 동남아 수출을 나타내는 KOSIS 집계 분류코드가 없음 |
| 판단불가_KOSIS기여도미제공 | 1 | 가공식품 상승률은 확인됐지만 전체 물가 기여도 자료가 없음 |
| 재검토필요_정확시점불일치 | 22 | 정확한 목표 시점으로 재조회한 KOSIS 값과 주장 수치가 다름 |
| 판단불가_전망문장 | 8 | 전망/예상/목표 문장으로 현재 실적값 검증 대상이 아님 |
| 판단불가_정확시점조회실패 | 7 | 정확한 목표 시점의 KOSIS 값을 조회하거나 증감을 계산하지 못함 |
| 판단불가_파라미터미확정 | 3 | obj_l1/itm_id 등 필수 파라미터 미확정 |

## 산출 파일

- `outputs/bteam_review/submission_match_candidates.csv`: 수치상 일치하지만 매핑 수동 확정이 남은 claim
- `outputs/bteam_review/submission_match_candidates_manual_reviewed.csv`: 33건 전체 수동 판정과 근거
- `outputs/bteam_review/submission_confirmed_matches.csv`: 수동 확정 일치 15건
- `outputs/bteam_review/submission_match_candidates_recheck.csv`: 재매핑 필요 8건
- `outputs/bteam_review/submission_match_candidates_unverifiable.csv`: KOSIS 직접검증 불가 10건
- `outputs/bteam_review/final_verified_filled_2001_manual_v5.csv`: 수동 판정을 반영한 전체 2,001건
- `outputs/bteam_review/submission_match_candidates_manual_report.md`: 33건 상세 판정 보고서
- `outputs/bteam_review/submission_recheck_8_resolved.csv`: 재매핑 8건 최종 판정과 새 파라미터
- `outputs/bteam_review/submission_recheck_8_verified.csv`: 기존 검증기로 재확인한 확정 6건
- `outputs/bteam_review/submission_match_candidates_final_33_v6.csv`: 33건 최종 상태
- `outputs/bteam_review/submission_confirmed_matches_v6.csv`: 누적 확정 일치 21건
- `outputs/bteam_review/final_verified_filled_2001_remapped_v6.csv`: 재매핑을 반영한 전체 2,001건
- `outputs/bteam_review/submission_recheck_8_report.md`: 재매핑 8건 상세 보고서
- `outputs/bteam_review/submission_recheck_needed.csv`: 표/항목/시점/단위 재검토 필요 claim
- `outputs/bteam_review/submission_unverifiable.csv`: API/파라미터/증감 계산 문제로 판단불가 claim
- `outputs/bteam_review/final_verified_filled_2001_audited_v4.csv`: 전체 2,001건 상세 검증 결과
- `outputs/bteam_gold/gold100_selection.csv`: 5개 분야 균형 100건 선정 결과
- `outputs/bteam_gold/gold100_manual_labels.csv`: 100건 수동 확정 라벨·매핑·KOSIS 근거
- `outputs/bteam_gold/gold100_metrics.csv`: 현재 시스템 정확도 지표
- `outputs/bteam_gold/kosis_metric_codebook.csv`: 반복 지표 코드북
- `outputs/bteam_gold/exact_period_22_error_analysis.csv`: 정확시점 불일치 22건 최종 원인 분석
- `outputs/bteam_gold/expansion_1643_all.csv`: 1,643건 코드북 확대 결과
- `outputs/bteam_gold/expansion_batch_001.csv`~`expansion_batch_009.csv`: 100~200건 단위 검토 배치
- `outputs/bteam_gold/unavailable_337_categorized.csv`: 판단불가 337건 사유 분류
- `outputs/bteam_gold/final_verified_filled_2001_codebook_v7.csv`: 확대 결과를 합친 2,001건 최신본
- `outputs/bteam_gold/B팀_KOSIS_골드셋_및_확대검증.xlsx`: 대시보드와 전체 근거 시트
- `outputs/bteam_holdout/holdout100_selection.csv`: 개발용 골드와 중복 없는 독립 표본
- `outputs/bteam_holdout/holdout100_evaluation.csv`: 수동 골드 라벨과 동결 코드북 예측 전체
- `outputs/bteam_holdout/holdout100_metrics.csv`: 독립 평가 전체 지표
- `outputs/bteam_holdout/holdout100_error_analysis.csv`: 오류 75건과 원인
- `outputs/bteam_holdout/holdout100_improvement_backlog.csv`: 코드북 v2 개선 우선순위
- `outputs/bteam_holdout/B팀_KOSIS_독립홀드아웃_평가.xlsx`: 독립 평가 대시보드와 근거 시트

## A팀에 요청할 점

- 개별 상품 가격, 기업 실적, 전망/목표 문장처럼 KOSIS 공식 통계로 바로 검증하기 어려운 문장은 claim 후보에서 제외하거나 `verifiable=false`로 표시 필요.
- claim마다 실제 검증 대상 숫자(`target_number`)를 별도 컬럼으로 주면 날짜/순위/기간 숫자를 잘못 비교하는 문제가 크게 줄어듦.
- `전년동월 대비`, `전월 대비`, `작년`, `지난달`, `누적`, `1~9월` 같은 시점 기준을 별도 컬럼으로 분리해주면 API 파라미터 매칭 정확도가 올라감.

## B팀 다음 개선점

- P0: `C20191`의 과배제를 수정해 정책 배경 단어보다 명시적 KOSIS 지표 매핑을 우선한다.
- P1: 검증 가능 보류 26건과 검증 불가 보류 48건을 이용해 코드북 v2와 단위 테스트를 만든다.
- P2: 최신 출생 잠정치 표 탐색과 API 갱신 지연 재시도 큐를 구현한다.
- 코드북 v2를 고정한 뒤 현재 홀드아웃과 겹치지 않는 새 100건에서 80% 게이트를 재평가한다.
- 새 독립 평가 통과 전에는 수동검토 유지 1,281건을 자동 확정하지 않는다.

## 참고 카운트

- 기존 원격 자동 verdict(진단용): {'일치': 70, '불일치': 1621, '판단불가': 310}
- 70건 정확시점 재실행 verdict: 일치 35건, 불일치 26건, 판단불가 9건
- metric 상위: {'무역지표': 830, '비율·증감률': 574, '고용지표': 174, '임금·소득': 143, '물가지표': 134, '인구지표': 71, '부동산지표': 21, '판매·생산량': 15, '금리지표': 8, '건수·개수': 7}
