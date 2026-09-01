# v31b API deployment report

## Deployment state

- Engine: `v31b_20260821_r1` (read-only source)
- Engine SHA-256: `3d2b7ebf51ec456ba9bf23525539b6e2e37bb3a9d28e5e90ac2ff1ced10bc8bf`
- Service: `kosis-v31b-api.service`
- Internal endpoint: `http://127.0.0.1:8000`
- Runtime check: NVIDIA L4, PostgreSQL `kosis_tables=107138`
- Worker policy: one Uvicorn worker and one FIFO GPU queue
- Supported now: `input_stage=measurements`
- Raw claim mode: add `CLOVA_API_KEY` to `/home/ubuntu/kosis-project/.env`, then restart the service

The one-row end-to-end smoke test passed through prepare, Stage A legacy/balanced, Stage B, Stage C, KOSIS API verification, and result serialization. It returned `MATCH / VERIFIED_MATCH` with official table `TX_36501_A653`.

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
