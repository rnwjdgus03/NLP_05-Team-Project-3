# v60 운영·재현 Runbook

## 공개 저장소와 서버 런타임

GitHub에는 코드와 작은 평가 근거만 둡니다. 다음 자산은 서버 또는 팀 공유 저장소에서 별도 관리합니다.

- BGE-M3 표 인덱스: `tables.csv`, `embeddings.npy`, `manifest.json`
- PostgreSQL `kosis_project`
- `.env`의 HCX/KOSIS/서비스 키
- 모델 캐시와 실행 결과

공개 스냅샷은 `freezes/v60_service_candidate_20260824_r1`이며 `PUBLICATION_MANIFEST.json`에서 제거·정제 내역을 확인할 수 있습니다.

## 필수 런타임 확인

```bash
nvidia-smi
psql -d kosis_project -Atqc 'select count(*) from kosis_tables'
python - <<'PY'
import numpy as np
print(np.load('indexes/bge_m3_table_v2_complete/embeddings.npy', mmap_mode='r').shape)
PY
```

참고 운영값은 KOSIS 표 107,138건, BGE 임베딩 `(107138, 1024)`입니다.

## 환경변수 원칙

실제 값은 `.env`에만 두고 커밋하지 않습니다.

```text
CLOVA_API_KEY=...
KOSIS_API_KEY=...
KOSIS_SERVICE_API_KEY=...
KOSIS_POSTGRES_DSN=postgresql:///kosis_project
KOSIS_EXPECTED_FREEZE_ID=v60_service_candidate_20260824_r1
KOSIS_EXPECTED_CODE_SHA256=743360d418f5173bfa8445f0e25126a5bd20320967a21398388538ff964f3cef
```

발표자료·이슈·채팅에 IP, 비밀번호, API 키, PEM을 넣지 않습니다. 노출 가능성이 있었던 키는 재사용하지 않고 교체합니다.

## 서비스 기동 원칙

- API worker 1개
- GPU pipeline worker 1개
- BFF 1개
- 같은 GPU에서 BGE/reranker 실험 두 개 동시 실행 금지
- 같은 KOSIS 키로 대량 API 검증 두 개 동시 실행 금지

서비스는 동결 ID와 엔진 SHA를 확인한 뒤 기동해야 합니다. 공개 스냅샷은 비밀값이 제거돼 있으므로 서버 원본 동결본과 외부 자산이 없으면 전체 추론이 실행되지 않습니다.

## 로컬 접속

서버가 localhost에만 바인딩된 경우 SSH 터널을 사용합니다.

```powershell
ssh -N -L 13100:127.0.0.1:3100 `
  -i "$env:USERPROFILE\.ssh\3rd.pem" `
  ubuntu@SERVER_IP
```

그 후 브라우저에서 `http://127.0.0.1:13100`을 엽니다.

## 결과 확인 체크리스트

1. `/readyz`가 `status=ready`와 정확한 v60 freeze ID를 반환
2. 기사 URL 수집 성공
3. HCX 추출 결과에 기간·값·단위 존재
4. READY/ENRICH/REJECT 집계 존재
5. Stage A/B/C 후보 및 PostgreSQL preflight 존재
6. KOSIS 근거에 tbl_id·ITEM·OBJ·period·unit 기록
7. 불확실한 좌표에서 자동 VALUE_MISMATCH가 차단됨
8. 실행 manifest에 코드·인덱스·입력 SHA 기록

## GitHub 공개 전 점검

```bash
git diff --cached --check
git grep -n -E 'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|CLOVA_API_KEY=[^.]|KOSIS_API_KEY=[^.]'
git status --short
```

DB, 인덱스, ZIP/TAR, `.env`, PEM, 실행 결과가 staged 되면 제거합니다.
