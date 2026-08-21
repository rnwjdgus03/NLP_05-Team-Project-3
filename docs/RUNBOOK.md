# 실행 및 운영 가이드

기준 서버 경로는 `/home/ubuntu/kosis-project`, OS는 Ubuntu 24.04, GPU는 NVIDIA L4입니다.

## 1. 필수 외부 자산

Git clone 후 다음 항목을 별도로 배치합니다.

```text
/home/ubuntu/kosis-project/indexes/bge_m3_table_v2_complete/tables.csv
/home/ubuntu/kosis-project/indexes/bge_m3_table_v2_complete/embeddings.npy
/home/ubuntu/kosis-project/indexes/bge_m3_table_v2_complete/manifest.json
PostgreSQL database: kosis_project
```

인덱스와 DB snapshot은 크기 때문에 Git에 올리지 않습니다. 운영 기준 행 수는 다음과 같습니다.

```text
tables.csv rows                 107138
embeddings.npy shape           107138 x 1024
PostgreSQL kosis_tables        107138
PostgreSQL kosis_axis_values   9663625
```

## 2. Python 환경

```bash
cd /home/ubuntu/kosis-project
python3 -m venv .venv
.venv/bin/python -m pip install -U pip setuptools wheel
.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cu128
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install -r service_api/requirements.txt
```

## 3. 환경변수

```bash
cp .env.example .env
chmod 600 .env
```

필수 비밀값은 `CLOVA_API_KEY`, `KOSIS_API_KEY`, `KOSIS_SERVICE_API_KEY`입니다. 실제 값은 문서, Git, 단체 채팅에 남기지 않습니다.

```bash
read -rsp "CLOVA API key: " VALUE; echo
printf 'CLOVA_API_KEY=%s\n' "$VALUE" >> .env
unset VALUE
chmod 600 .env
```

KOSIS 키와 서비스 키도 같은 방식으로 입력합니다. 같은 키를 여러 번 추가했다면 마지막 값이 적용되므로 중복 행을 정리합니다.

## 4. 동결 엔진 확인

```bash
cd /home/ubuntu/kosis-project
cat freezes/v31b_20260821_r1/freeze_manifest.json
find freezes/v31b_20260821_r1 -type f -exec chmod a-w {} +
```

기대값:

```text
freeze_id: v31b_20260821_r1
code_tree_sha256: 3d2b7ebf51ec456ba9bf23525539b6e2e37bb3a9d28e5e90ac2ff1ced10bc8bf
```

## 5. systemd 서비스

Node.js 22가 `/home/ubuntu/kosis-project/tools/node/bin/node`에 연결돼 있다고 가정합니다.

```bash
sudo cp service_api/deploy/kosis-v31b-api.service /etc/systemd/system/
sudo cp frontend_server/deploy/kosis-frontend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kosis-v31b-api kosis-frontend
```

확인:

```bash
systemctl is-active kosis-v31b-api kosis-frontend
curl -fsS http://127.0.0.1:8000/readyz
curl -fsS http://127.0.0.1:3100/healthz
nvidia-smi
```

로그:

```bash
sudo journalctl -u kosis-v31b-api -f
sudo journalctl -u kosis-frontend -f
```

## 6. 개발 접속

Windows PowerShell에서 실행합니다.

```powershell
ssh -N -L 13100:127.0.0.1:3100 `
  -i "$env:USERPROFILE\.ssh\3rd.pem" `
  ubuntu@SERVER_IP
```

명령이 출력 없이 계속 실행되면 정상입니다. 브라우저에서 `http://127.0.0.1:13100`을 엽니다.

## 7. 테스트

```bash
cd /home/ubuntu/kosis-project/service_api
../.venv/bin/python -m pytest -q tests
cd /home/ubuntu/kosis-project/freezes/v31b_20260821_r1
../../.venv/bin/python -m pytest -q tests
cd /home/ubuntu/kosis-project
/home/ubuntu/kosis-project/tools/node/bin/node --check frontend_server/server.mjs
```

실제 기사 URL 테스트는 비용과 API 호출을 발생시키므로 한 건씩 실행합니다. GPU 작업 두 개와 동일 KOSIS 키를 사용하는 검증 두 개를 동시에 실행하지 않습니다.

## 8. 공개 전 필수 작업

- 도메인과 TLS 인증서
- Nginx reverse proxy
- 사용자 인증 또는 제한된 초대 접근
- IP/사용자별 rate limit
- 기사 수집 허용 정책과 이용약관 검토
- 로그에서 기사 원문과 비밀정보 마스킹
- 모니터링, 백업, 장애 복구 절차
