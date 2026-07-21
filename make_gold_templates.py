"""골드 라벨 템플릿 생성기.

파이프라인 산출물에서 사람이 채울 골드 시트 2종을 만든다. 모델 예측값을 미리
채워두고, 빈 gold_ 컬럼만 라벨러가 채우게 한다. 채점은 score_gold.py가 한다.

시트 A (claim 단위, is_claim):   gold_is_claim.csv
시트 B (measurement 단위):        gold_measurement.csv   (게이트+검색+판정 골드)

사용법:
  python make_gold_templates.py \
    --extract hcx_v15.csv \
    --ready outputs/runs/hcx_v15_kosis_ready.csv \
    --candidates outputs/runs/hcx_v15_kosis_table_candidates.csv \
    --isclaim-diff is_claim_005vs007_v12_diff28.csv \
    --out-dir outputs/gold

--ready/--candidates 는 없으면 건너뛴다(추출만으로도 시트 B 골격은 생성).
"""
import argparse
import csv
from pathlib import Path

csv.field_size_limit(2 ** 31 - 1)


def read(path):
    if not path or not Path(path).exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write(path, rows, fields):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {len(rows):>4} rows -> {path}")


def build_isclaim(diff_path, out_dir):
    rows = read(diff_path)
    if not rows:
        print("[A] is_claim diff 파일 없음, 건너뜀")
        return
    # gold_label 컬럼이 이미 있으면 유지, 없으면 추가
    fields = list(rows[0].keys())
    if "gold_label" not in fields:
        fields.append("gold_label")
        for r in rows:
            r["gold_label"] = ""
    write(out_dir / "gold_is_claim.csv", rows, fields)
    filled = sum(1 for r in rows if str(r.get("gold_label", "")).strip())
    print(f"[A] is_claim 골드: {len(rows)}건 중 {filled}건 이미 채워짐. "
          f"gold_label(True/False) 채우면 됨. 랜덤 100건 별도 라벨 권장.")


def build_measurement(extract_path, ready_path, cand_path, out_dir):
    ext = read(extract_path)
    if not ext:
        print("[B] 추출 파일 없음, 건너뜀")
        return
    ready_ids = {r.get("claim_measurement_id") for r in read(ready_path)}
    # 검색 후보에서 measurement별 후보 tbl_id 목록(rank순)을 참고용으로 붙임
    cand_by_m = {}
    for c in read(cand_path):
        mid = c.get("claim_measurement_id")
        cand_by_m.setdefault(mid, []).append(
            f"{c.get('candidate_rank', '?')}:{c.get('tbl_id', '')}")

    keep = ["claim_id", "claim_measurement_id", "claim_text", "date",
            "measurement_text", "measurement_usage", "claim_domain_scope",
            "measurement_binding_source", "measurement_role",
            "measurement_indicator", "measurement_item",
            "value", "unit", "measurement_period", "measurement_prd_se"]
    gold_cols = ["in_ready", "cand_tbl_ids",
                 "gold_verifiable", "gold_measurement_correct",
                 "gold_org_id", "gold_tbl_id", "gold_obj_l1", "gold_itm_id",
                 "gold_verdict", "gold_actual_value"]
    fields = keep + gold_cols

    rows = []
    for r in ext:
        mid = r.get("claim_measurement_id", "")
        if not mid or mid == "-":
            continue  # 측정값 없는 placeholder 행 제외
        row = {k: r.get(k, "") for k in keep}
        row["in_ready"] = "Y" if mid in ready_ids else "N"
        row["cand_tbl_ids"] = " | ".join(cand_by_m.get(mid, [])[:10])
        for g in gold_cols[2:]:
            row[g] = ""
        rows.append(row)
    write(out_dir / "gold_measurement.csv", rows, fields)
    n_ready = sum(1 for r in rows if r["in_ready"] == "Y")
    print(f"[B] measurement 골드: 전체 {len(rows)}행 (ready {n_ready}행).")
    print("    - gold_verifiable/gold_measurement_correct: 전체 행에 채움 (게이트 recall용)")
    print("    - gold_tbl_id 등 검색·판정 골드: ready 행에만 채우면 됨")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", default="hcx_v15.csv")
    ap.add_argument("--ready", default="")
    ap.add_argument("--candidates", default="")
    ap.add_argument("--isclaim-diff", default="is_claim_005vs007_v12_diff28.csv")
    ap.add_argument("--out-dir", default="outputs/gold")
    a = ap.parse_args()
    out_dir = Path(a.out_dir)
    build_isclaim(a.isclaim_diff, out_dir)
    build_measurement(a.extract, a.ready, a.candidates, out_dir)
    print(f"\n완료 → {out_dir}/  (gold_ 컬럼만 채우고 score_gold.py로 채점)")


if __name__ == "__main__":
    main()
