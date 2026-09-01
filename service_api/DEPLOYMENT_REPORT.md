# v64 API deployment report

## 최종 상태

- 엔진: `v64_candidate_20260824_r1` (읽기 전용)
- 엔진 SHA-256: `760033bbd941a26acd6af1fc0360ef9665ae78d46adc81e80f901c80ce5a7d64`
- 내부 API: `http://127.0.0.1:8002`
- 내부 프론트: `http://127.0.0.1:3102`
- 런타임: NVIDIA L4, PostgreSQL `kosis_tables=107138`
- 정책: Uvicorn worker 1개, FIFO GPU 큐 1개
- 지원 입력: `claims`, `measurements`, 프론트 BFF의 조선일보 URL

`v66_final_service_url50_20260824_r1`에서 원본 `chosun_full.csv` 기반 잠금 URL 50건이 모두 수집·처리되었습니다. KOSIS-ready 측정값 96개 중 최종 선택 근거는 11개, 근거 기사는 5건, 작업시간 p95는 290.36초였습니다. 자세한 결과는 `evaluation/v66_locked_url50/`에 있습니다.

## 시작과 상태 확인

```bash
cd /home/ubuntu/kosis-project
./cloud_setup/start_v64_final_api.sh
./cloud_setup/start_v64_final_frontend.sh
curl -fsS http://127.0.0.1:8002/readyz
curl -I http://127.0.0.1:3102/
```

## 외부 공개 전 안전한 접속

```powershell
ssh -N -L 18002:127.0.0.1:8002 -L 13100:127.0.0.1:3102 `
  -i "C:\Users\사용자\.ssh\3rd.pem" `
  ubuntu@SERVER_IP
```

브라우저에서는 `http://127.0.0.1:13100`을 엽니다. `.env`, 서비스 키, KOSIS 키와 CLOVA 키는 브라우저 코드나 저장소에 넣지 않습니다. 공개 배포 시에는 도메인, HTTPS, CORS 허용 목록, rate limit을 별도로 설정합니다.

## 해석 주의

v65 신규 blind100은 사전 검색 목표에 실패했습니다. 이 배포는 기능·안전성·E2E 완주를 보여주는 PoC 데모 후보이며, 블라인드 정확도 목표 통과를 주장하지 않습니다.