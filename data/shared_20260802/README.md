# 공유 산출물 (2026-08-02 기준)

병렬 작업용으로 **KOSIS API 호출 없이 재현할 수 있는 최소 데이터**를 모았다.
Chroma 인덱스(0.5~1GB)와 원본 기사는 여기 없다 — 아래 「없는 것」 참고.

## 현재 지표

| | |
|---|---|
| 평가 집합 | **88** (`evaluation_set_v6.csv`) |
| 확정 (READY/PROVISIONAL) | **17** — 전체 19.3% · 확인 가능 26.6% |
| 판정 | 일치 7 · 판정보류 3 · 판단불가 7 · **불일치 0** |
| 골드 좌표 | 12 |
| 테스트 | 802 |

**숫자만 보면 오해한다.** 88건 중 24건은 원리상 확인 불가(기사 시점에 미발표 등)다.
그리고 이날 아침에도 확정은 12건이었는데 **그중 불일치 3건이 전부 오판**이었다.
지금은 17건에 거짓 불일치 0이다. **커버리지보다 정밀도가 먼저다.**

## 파일

| 파일 | 무엇 |
|---|---|
| `evaluation_set_v6.csv` | **현재 기준 88건.** 모든 지표의 분모 |
| `evaluation_set_v5_manifest.json` | 177 → 88 로 무엇을 왜 뺐는지, 게이트 규칙 스냅샷 |
| `evaluation_set_v5_excluded.csv` | 제외된 89건과 사유 |
| `gold_confirmed_v3.csv` | 골드 좌표 12건 (값 재현으로 확인된 것만) |
| `silver_coordinates_v3.csv` | 실버 라벨. `tier` 로 신뢰도 구분 |
| `coverage_report_v10.csv` | 88건의 버킷 분류 (확정 / 확인 불가 / 시스템 한계) |
| `verified_v10.csv` | 확정 17건의 판정 결과 |
| `05_hcx_measurements_kosis_ready.csv` | 1차 READY 177건 (게이트 적용 전) |
| `05_hcx_measurements_kosis_table_candidates.csv` | 상류 표 후보 |
| `05_hcx_measurements_kosis_meta_index.csv` | KOSIS 메타 (3.7MB). 좌표 진단에 필수 |

## 어떤 순서로 쓰나

**API 없이 되는 것** — 아래는 CSV만 읽는다.

```bash
python report_coverage.py \
  --validated <chroma_validated.csv> \
  --evaluation-set data/shared_20260802/evaluation_set_v6.csv \
  --article-source data/shared_20260802/05_hcx_measurements_kosis_ready.csv \
  --probe <no_data_probe.csv> \
  --output coverage.csv

python diagnose_coordinate_space.py \
  --meta-index data/shared_20260802/05_hcx_measurements_kosis_meta_index.csv \
  --evaluation-set data/shared_20260802/evaluation_set_v6.csv \
  --candidates <chroma_candidates.csv> --label C --output coord.csv
```

`report_coverage.py` 를 먼저 보는 것을 권한다. 결과를 **`확정` / `확인 불가` / `시스템 한계`** 로
가르는데, `확인 불가`는 실패가 아니라 "KOSIS 에 그 시점 데이터가 없다"는 결론이다.
둘을 섞으면 시스템이 실제보다 못해 보이고 어디를 고쳐야 하는지도 흐려진다.

**API 가 필요한 것** — `kosis_validate_mapping_candidates.py`, `kosis_verify_claim_values.py`,
`build_silver_coordinates.py`, `probe_empty_coordinates.py`.

## 재현할 때 반드시 알아야 할 것

**측정 노이즈가 두 가지 있다. 한 번 돌린 숫자를 그대로 인용하면 안 된다.**

| 노이즈원 | 크기 | 대응 |
|---|---|---|
| Chroma 인덱스 재빌드 | 골드 12건에서 ±1건 (±8.3%p) | A/B 비교 중에는 재빌드하지 말 것 |
| KOSIS API 일시 실패 | 확정 ±1~2건 | `API_ERROR` 가 0 이 될 때까지 validate 재실행 |

실측 사례: 같은 입력으로 validate 를 두 번 돌렸더니 `API_ERROR` 48행 → 0,
확정 11 → 12 였다. 재시도·백오프가 이미 들어 있는데도 그렇다.
`report_coverage.py` 가 `API_ERROR` 잔존 시 경고한다.

## 없는 것

| | 왜 |
|---|---|
| `.env` (`CLOVA_API_KEY`, `KOSIS_API_KEY`) | 각자 발급받아 쓸 것. 절대 커밋 금지 |
| Chroma 인덱스 (`data/indexes/`) | 0.5~1GB. `kosis_build_chroma_meta_index.py` 로 재생성 |
| 원본 기사 전문 | 용량. `03_claim_contexts.csv` 는 Drive 에만 |
| 좌표 후보·검증 결과 | 인덱스에 의존해 재생성됨. 필요하면 요청할 것 |

인덱스를 재생성하면 `chroma_manifest.json` 의 `embedding_fingerprint` 로
같은 인덱스인지 확인할 수 있다. 지문이 다르면 숫자를 직접 비교하지 말 것.

## 배경 문서

`docs/chroma_hybrid_mapping_20260731.md` 의 **맨 위 「현재 상태」 섹션만** 보면 된다.
본문은 시간순 기록이라 **철회된 결론이 그대로 남아 있다** —
특히 3차의 "ChromaDB 를 접는다"는 결론은 4차에서 뒤집혔고 유효하지 않다.

주제별로는 `docs/골드확장_한계_20260802.md`(골드가 12건에서 막힌 이유),
`docs/범위검수_67문장_20260802.md`(어떤 주장이 KOSIS 범위 밖인가).
