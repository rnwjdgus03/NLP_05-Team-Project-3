# v31b API deployment report

## Deployment state

- Engine: `v31b_20260821_r1` (read-only source)
- Engine SHA-256: `3d2b7ebf51ec456ba9bf23525539b6e2e37bb3a9d28e5e90ac2ff1ced10bc8bf`
- Service: `kosis-v31b-api.service`
- Internal endpoint: `http://127.0.0.1:8000`
- Runtime check: NVIDIA L4, PostgreSQL `kosis_tables=107138`
- Worker policy: one Uvicorn worker and one FIFO GPU queue
- Supported: `input_stage=measurements`, `input_stage=claims`
- URL input: `frontend_server`가 기사에서 raw claim을 자동 생성

실제 기사 URL 테스트가 기사 수집, HCX, Stage A legacy/balanced, Stage B, Stage C, KOSIS API 검증, 결과 직렬화를 통과했습니다. 2024년 수출액은 공식 KOSIS 값과 `MATCH / VERIFIED_MATCH`로 완료됐습니다.

## Safe access before HTTPS

Keep the API bound to localhost and use an SSH tunnel during development:

```powershell
ssh -N -L 8000:127.0.0.1:8000 `
  -i "C:\Users\김진성\.ssh\3rd.pem" `
  ubuntu@SERVER_IP
```

Then open `http://127.0.0.1:8000/docs`. Do not put the service API key in browser source. A frontend server/BFF should keep it in an environment variable and proxy requests; see `deploy/frontend_server_client.ts`.

## Operations

```bash
sudo systemctl status kosis-v31b-api
sudo journalctl -u kosis-v31b-api -f
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
```

To enable raw HCX extraction without printing the secret:

```bash
cd /home/ubuntu/kosis-project
read -rsp "CLOVA API key: " CLOVA_KEY
echo
printf '\nCLOVA_API_KEY=%s\n' "$CLOVA_KEY" >> .env
unset CLOVA_KEY
chmod 600 .env
sudo systemctl restart kosis-v31b-api
curl http://127.0.0.1:8000/readyz
```

Before public frontend connection, configure a domain, HTTPS, frontend origin allowlist, reverse-proxy rate limiting, and a server-side frontend proxy. Plain HTTP is intentionally not enabled for authenticated article traffic.
