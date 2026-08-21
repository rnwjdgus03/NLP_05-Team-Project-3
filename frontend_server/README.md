# URL 전용 검증 프론트/BFF

사용자는 기사 URL 하나만 입력합니다. BFF가 공개 HTML에서 제목·날짜·본문을 읽고 수치 주장을 최대 8개까지 골라 내부 v31b API에 전달합니다.

- UI/BFF: `127.0.0.1:3100`
- 내부 API: `127.0.0.1:8000`
- Node.js 22, 외부 npm 의존성 없음
- 브라우저에는 HCX, KOSIS, 서비스 API 키를 전달하지 않음
- 공개 HTTP/HTTPS만 허용하고 사설·loopback·link-local 주소 차단

개발 접속:

```powershell
ssh -N -L 13100:127.0.0.1:3100 `
  -i "$env:USERPROFILE\.ssh\3rd.pem" `
  ubuntu@SERVER_IP
```

브라우저에서 `http://127.0.0.1:13100`을 엽니다. 로그인·구독 또는 JavaScript 전용 본문은 수집하지 못할 수 있습니다.
