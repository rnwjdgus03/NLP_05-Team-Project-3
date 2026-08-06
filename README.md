# 📥 다운로드 / 클론 시 유의사항

이 문서는 저장소를 새로 클론하거나 `git pull`로 최신 내용을 받는 팀원을 위한 안내입니다.
최근 `Chatbot` 브랜치를 정리하면서 **대용량 파일 2개가 git 추적에서 제외**되었으니, 아래 내용을 꼭 확인해 주세요.

---

## ⚠️ 1. Git에 포함되지 않은 대용량 파일

GitHub 용량 제한(100MB 하드 리밋, 50MB 권장치) 때문에 아래 두 파일은 **`.gitignore`에 등록되어 커밋에서 빠졌습니다.**
즉, 저장소를 새로 클론해도 이 파일들은 로컬에 생성되지 않습니다.

| 파일 경로 | 용량 | 제외 이유 |
|---|---|---|
| `화면을부탁해/조선_원본_데이터.csv` | 약 85.5MB | GitHub 권장 용량(50MB) 초과 |
| `화면을부탁해/kosis_numpy/kosis_numpy_db/embeddings.npy` | 약 157MB | GitHub 하드 리밋(100MB) 초과 → push 자체가 차단됨 |

### 클론 후 이 파일들이 없으면 발생하는 문제
- `kosis_numpy` 관련 검색/매핑 스크립트(`kosis_numpy/map_kosis_candidates.py` 등)를 그냥 실행하면 `embeddings.npy`를 찾지 못해 **파일 없음(FileNotFoundError) 오류**가 날 수 있습니다.
- `조선_원본_데이터.csv`를 참조하는 전처리/크롤링 스크립트도 동일하게 실패할 수 있습니다.

### 확보 방법 (택 1)
1. **팀 공유 드라이브(구글드라이브 등)에서 직접 다운로드** 받아 동일한 경로에 그대로 넣기
   - `embeddings.npy` → `화면을부탁해/kosis_numpy/kosis_numpy_db/` 폴더에 위치
   - `조선_원본_데이터.csv` → `화면을부탁해/` 폴더에 위치
2. **스크립트로 재생성**
   - `embeddings.npy`는 `화면을부탁해/kosis_numpy/build_kosis_numpy.py`에서 생성하는 파일로 보입니다. 재실행 전 스크립트 상단 docstring/인자를 먼저 확인해 주세요 (원본 KOSIS 메타데이터·모델 다운로드가 선행되어야 할 수 있습니다).
   - `조선_원본_데이터.csv`는 원본 크롤링 결과이므로, 정확한 재수집 방법은 이 파일을 만든 팀원에게 먼저 확인하는 걸 권장합니다.

> 💡 둘 중 하나라도 확보하면, **절대 `git add .`로 다시 커밋하지 마세요.** `.gitignore`에 등록은 되어 있지만, 강제로 `git add -f`를 쓰면 다시 push가 막힙니다.

---

## 2. 클론 후 체크리스트

```powershell
# 1) 저장소 클론
git clone https://github.com/rnwjdgus03/NLP_05-Team-Project-3.git
cd NLP_05-Team-Project-3

# 2) 작업 브랜치로 전환
git checkout Chatbot

# 3) 의존성 설치 (경로 주의: 코드가 화면을부탁해/ 폴더 하위로 이동했습니다)
cd 화면을부탁해
pip install -r requirements.txt

# 4) 환경변수 파일 준비
copy .env.example .env
# .env 안의 API 키 등 값을 직접 채워주세요 (.env는 git에 커밋되지 않습니다)

# 5) 위 1번 항목의 대용량 파일 2개를 별도로 받아 제자리에 위치시키기

# 6) 서버 실행
python -m uvicorn chatbot.api:app --reload
```

---

## 3. 저장소 구조가 바뀌었어요

최근 리팩터링 커밋으로 대부분의 코드/데이터가 저장소 루트에서 **`화면을부탁해/`** 폴더 하위로 이동했습니다.
기존에 로컬에서 루트 기준 상대경로로 스크립트를 실행하고 있었다면, 경로를 `화면을부탁해/` 기준으로 다시 확인해야 합니다.

또한 `chatbot/`(신규)과 `legacy/chatbot_1_ui/`(과거 버전)가 함께 들어있으니, **실행할 때는 `chatbot/api.py` 쪽이 최신 버전**이라는 점을 헷갈리지 않도록 주의하세요.

---

## 4. Git 관련 추가 주의사항

- 이 브랜치(`Chatbot`)는 최근 `git rebase`로 히스토리가 정리된 적이 있습니다. 이미 로컬에 예전 `Chatbot` 브랜치를 받아둔 팀원은 `git pull`이 아니라,
  ```powershell
  git fetch origin
  git reset --hard origin/Chatbot
  ```
  로 브랜치를 원격과 동일하게 맞추는 걸 권장합니다. (⚠️ 로컬에 저장 안 된 변경사항이 있다면 먼저 커밋/백업하세요.)
- `git status`에서 대용량 파일이 `staged`로 잡히는 걸 보게 되면, 커밋하지 말고 `.gitignore`에 경로가 있는지 먼저 확인하세요.
- 커밋 메시지 편집기가 Vim으로 뜨는 게 익숙하지 않다면 아래로 메모장으로 바꿔둘 수 있습니다.
  ```powershell
  git config --global core.editor notepad
  ```

---

## 5. 요약

- [ ] `embeddings.npy`, `조선_원본_데이터.csv` 두 파일은 클론만으로는 안 받아짐 → 별도로 받아서 채워넣기
- [ ] 코드 실행 경로는 `화면을부탁해/` 기준
- [ ] `.env`는 `.env.example` 복사해서 직접 채우기
- [ ] 대용량 데이터 파일은 절대 강제로 `git add -f` 하지 않기
