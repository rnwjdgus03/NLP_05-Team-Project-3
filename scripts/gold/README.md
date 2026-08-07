# Gold builders

자동 골드 CSV·manifest와 검토용 Excel을 만드는 도구다. 저장소 루트에서 실행한다.

```powershell
python scripts/gold/build_mcp_auto_gold_v3.py
python scripts/gold/build_mcp_auto_gold_200.py
node scripts/gold/build_mcp_auto_gold_200_workbook.mjs
```

CSV와 manifest는 `data/gold/`, 검토용 Excel은 `outputs/gold/`에 생성한다.
일부 생성기는 로컬 파이프라인 산출물을 입력으로 사용하므로 필요한 입력이 없으면 먼저 해당 실행을 재현해야 한다.
