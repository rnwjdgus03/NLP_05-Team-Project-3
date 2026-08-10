# 홀드아웃8 v5 — KOSIS MCP 실제 좌표 평가

## 결론

- Top-5와 Top-10은 실제 MCP 골드 9건에서 완전히 같은 결과를 냈다.
- 표 Recall@5와 Recall@10은 모두 22.22%(2/9)다.
- 최종 표 정확도, ITEM 정확도, 전체 좌표 정확도는 모두 0%(0/9)다.
- 기간 정확도만 55.56%(5/9)다.
- 후보 수를 5개에서 10개로 늘리는 것만으로는 개선이 없으며, 표 검색 질의와 ITEM/OBJ/기간 결합 로직을 먼저 수정해야 한다.

## 입력 무결성

- 사용자 결과 ZIP: `holdout8_v5_gpu_results.zip`
- ZIP SHA-256: `38663cc6a313e285e16b69b698d3ffbe799e414f13d2affe5c1d51f267be49c1`
- ZIP 크기: 1,528,182 bytes
- 압축 파일: 35개
- API 오류: 0건

## 파이프라인 산출량

| 단계 | 행 수 | 고유 claim | 고유 measurement |
|---|---:|---:|---:|
| 기사 | 48 | - | - |
| 문장 | 1,054 | 1,054 | - |
| claim context | 324 | 324 | - |
| HCX measurement | 791 | 324 | 768 |
| KOSIS-ready | 135 | 63 | 135 |
| KOSIS-enrich | 336 | 180 | 315 |
| KOSIS-reject | 320 | 178 | 319 |
| 잠금 평가 집합 | 135 | 63 | 135 |

## 게이트 점검

- KOSIS-ready 135건에서 회사채·은행채·한전채·통안채·특수채·기업어음·전자단기사채·연결 기준 매출·영업이익 패턴은 0건이다.
- 회사 매출·회사채 제외 게이트는 이번 홀드아웃에서 의도대로 작동했다.
- 다만 파생 증감률과 KOSIS와 정의가 다른 지자체 자체 집계가 READY에 남아 있어 후속 게이트 강화가 필요하다.

## 층화 유지와 평가 가능성

| 층 | 원본 기사 | READY 기사 | READY measurement | MCP 실제 골드 |
|---|---:|---:|---:|---:|
| 국가 | 12 | 2 | 2 | 0 |
| 연령 | 12 | 4 | 26 | 2 |
| 성별 | 12 | 8 | 86 | 5 |
| 품목 | 12 | 4 | 21 | 2 |

- 입력 홀드아웃 자체는 국가·연령·성별·품목 각각 12건으로 균형을 유지했다.
- 게이트와 실제 KOSIS 조회를 통과한 분모는 성별에 치우쳤고 국가 층은 0건이 됐다.
- 국가 층의 `순수출 성장 기여도 0%`는 KOSIS의 2021년 순수출 성장기여도 0.6%p와 단위·값이 달랐고, `대멕시코 투자`는 KOSIS 공식 통계 수치로 확정하지 못했다.

## MCP 실제 골드

- KOSIS MCP `search → validate → get_data`가 모두 성공하고 좌표가 확정된 9건만 골드로 채택했다.
- 사람 검수 정답을 사용하지 않았으며 `human_reviewed=N`으로 기록했다.
- 실제 골드 좌표는 기업특성별 수출액 1건, 근로형태별 임금 증감 2건, 혼인 건수 2건, 월별 경상수지 2건, 25~29세 학력별 실업률 2건이다.
- 자동 골드 SHA-256: `d62fd028e9ea6ecb3f1ee80865ba1fb4db7e2c792861046bd215e917f8291846`

## 실제 조회에서 제외한 대표 사례

- 대전시 혼인 3건은 기사 값 499·679·1,133건과 KOSIS 2024년 8~10월 값 472·621·924건이 달라 같은 정의의 관측값으로 확정하지 않았다.
- 혼인·수출·벼 재배면적의 증감률은 KOSIS 표의 직접 ITEM이 아니라 두 시점 값으로 계산하는 파생값이라 좌표 골드에서 제외했다.
- 2017년 생산연령인구 기사 값 3,686만명은 현재 장래인구추계 표의 3,757.2만명과 달라 해당 표 좌표를 골드로 강제하지 않았다.

## Top-5 / Top-10 재평가

| 지표 | Top-5 | Top-10 | 차이 |
|---|---:|---:|---:|
| Mapping coverage | 100.00% | 100.00% | 0.00%p |
| Table recall | 22.22% | 22.22% | 0.00%p |
| Final table accuracy | 0.00% | 0.00% | 0.00%p |
| ITEM accuracy | 0.00% | 0.00% | 0.00%p |
| Period accuracy | 55.56% | 55.56% | 0.00%p |
| Full-coordinate accuracy | 0.00% | 0.00% | 0.00%p |

- 후보 안에 정답 표가 있었던 것은 임금 2건뿐이지만 2단계 선택기가 다른 표를 최종 선택했다.
- 9건 모두 최종 표 선택이 틀려 ITEM·OBJ까지 포함한 전체 좌표는 0건 정답이다.
- Top-5와 Top-10 선택은 135개 전체 평가 measurement에서 100% 일치했다.

## 오류 유형

| 주장 | 실제 표 | 예측 표 | 핵심 오류 |
|---|---|---|---|
| 기업특성별 수출액 | `DT_1TEC_P116` | `DT_1R11006_FRM101` | 기업특성별 표 대신 국가별 수출입 선택 |
| 근로형태별 임금 증감 | `DT_1DE7082S` | `DT_322002_B014` | 정답 표가 후보에 있었지만 최종 재순위 실패 |
| 연간·월간 혼인 건수 | `DT_1B8000G` | `DT_1B83A01` | 목적별 통합 시계열 대신 시도/시군구 표 선택 |
| 월별 경상수지 | `DT_301Y013` | `DT_301Y015` | 국제수지 대신 지역별 경상수지 선택 |
| 25~29세 학력별 실업률 | `DT_1DA7105S` | `DT_1DE9050S` | 연령·학력 OBJ가 있는 표를 검색하지 못함 |

## 다음 수정 우선순위

1. `통계명 + 조사명 + 대상 축`을 검색 질의에 함께 넣어 동일 지표의 유사 표를 구분한다.
2. 연령·성별·국가·품목 표지는 기사 층이 아니라 실제 measurement의 OBJ target 존재 여부로 다시 층화한다.
3. `증감률·성장기여도·증감`을 직접 ITEM과 계산형 파생값으로 분리해 계산형은 direct-coordinate READY에서 제외한다.
4. 기간 파서에서 기사 날짜의 `작년`, `지난 3월`을 월 단위로 보존해 연간 값으로 축약하지 않는다.
5. 정답 표가 후보에 있는 경우 ITEM/OBJ 일치 점수가 표 재순위 점수보다 우선하도록 2단계 선택기를 수정한다.

## KOSIS 출처

- [기업규모별 수출입](https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1TEC_P116&vw_cd=MT_ZTITLE&list_id=&seqNo=&lang_mode=ko&language=kor&obj_var_id=&itm_id=&conn_path=MT_ZTITLE)
- [근로형태별 월평균임금 및 증감](https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1DE7082S&vw_cd=MT_ZTITLE&list_id=&seqNo=&lang_mode=ko&language=kor&obj_var_id=&itm_id=&conn_path=MT_ZTITLE)
- [월·분기·연간 인구동향](https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1B8000G&vw_cd=MT_ZTITLE&list_id=&seqNo=&lang_mode=ko&language=kor&obj_var_id=&itm_id=&conn_path=MT_ZTITLE)
- [국제수지](https://kosis.kr/statHtml/statHtml.do?orgId=301&tblId=DT_301Y013&vw_cd=MT_ZTITLE&list_id=&seqNo=&lang_mode=ko&language=kor&obj_var_id=&itm_id=&conn_path=MT_ZTITLE)
- [연령/교육정도별 실업률](https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1DA7105S&vw_cd=MT_ZTITLE&list_id=&seqNo=&lang_mode=ko&language=kor&obj_var_id=&itm_id=&conn_path=MT_ZTITLE)
