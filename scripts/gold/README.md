# Gold builders

자동 골드 CSV·manifest와 검토용 Excel을 만드는 도구다. 저장소 루트에서 실행한다.

```powershell
python scripts/gold/build_mcp_auto_gold_v3.py
python scripts/gold/build_mcp_auto_gold_200.py
node scripts/gold/build_mcp_auto_gold_200_workbook.mjs
python scripts/gold/build_mcp_full_gold_200.py build --target-count 250
node scripts/gold/build_mcp_full_gold_200_workbook.mjs 250
```

CSV와 manifest는 `data/gold/`, 검토용 Excel은 `outputs/gold/`에 생성한다.
일부 생성기는 로컬 파이프라인 산출물을 입력으로 사용하므로 필요한 입력이 없으면 먼저 해당 실행을 재현해야 한다.
`mcp_full_gold_250`은 기존 200행을 그대로 보존하고, 저장된 KOSIS MCP
`kosis_get_data` 증거에서 동일 검증 조건을 통과한 다음 50행을 추가한다.
