# AI 기반 뉴스 수치 주장 사실검증 시스템

> **기업 요구사항 기반 NLP 프로젝트**
> **Status:** 🚧 In Progress

---

# 📖 Project Overview

본 프로젝트는 뉴스 기사에 포함된 **수치 기반 주장**을 KOSIS(Korean Statistical Information Service) 공식 통계와 비교하여 사실 여부를 자동으로 검증하는 AI 시스템을 개발하는 것을 목표로 합니다.

시스템은 뉴스 기사에서 검증 가능한 주장을 추출하고, 필요한 정보를 구조화한 뒤 KOSIS Open API를 활용하여 해당 통계를 조회합니다. 이후 통계값을 비교·분석하여 주장에 대한 검증 결과와 근거를 사용자에게 자연어 형태로 제공합니다.

---

# 🎯 Objectives

* 뉴스 기사에서 검증 가능한 수치 주장 탐지
* 주장에 포함된 핵심 정보(지표, 값, 단위, 시점, 지역 등) 추출
* KOSIS Open API를 활용한 통계 검색
* 통계 기반 수치 검증
* 근거를 포함한 Explainable AI 응답 생성

---

# 🏗️ System Architecture

```text
News Article
      │
      ▼
Claim Detection
      │
      ▼
Information Extraction
      │
      ▼
KOSIS Table Retrieval
      │
      ▼
KOSIS Open API
      │
      ▼
Numerical Verification
      │
      ▼
Explanation Generation
      │
      ▼
Chatbot Response
```

---

# ⚙️ Tech Stack

| Category        | Technology                   |
| --------------- | ---------------------------- |
| Language        | Python                       |
| Backend         | FastAPI                      |
| Data Processing | Pandas, NumPy                |
| NLP             | HuggingFace Transformers     |
| Retrieval       | Sentence Transformers, FAISS |
| LLM             | RAG-based Reasoning Model    |
| Data Source     | KOSIS Open API               |
| Version Control | Git, GitHub                  |

---

# 📂 Project Structure

```text
.
├── data/
│   ├── raw/
│   └── processed/
│
├── crawler/
│
├── preprocessing/
│
├── retrieval/
│
├── reasoning/
│
├── api/
│
├── frontend/
│
├── docs/
│
└── README.md
```

---

# 🔄 Development Process

## E1. Data Collection

* 뉴스 기사 수집
* 기사 전처리

## E2. Claim Detection

* 검증 가능한 수치 주장 탐지
* 주장 유형 분류

## E3. Information Extraction

* 지표
* 지역
* 시점
* 단위
* 수치
* 모집단 추출

## E4. Statistical Table Retrieval

* KOSIS 통계표 탐색
* 후보 통계표 검색

## E5. KOSIS API Retrieval

* KOSIS Open API 호출
* 통계 데이터 조회

## E6. Numerical Verification

* 기사 주장과 공식 통계 비교
* 계산 및 검증

## E7. Explainable Response

* 검증 결과 생성
* 근거 기반 자연어 설명 제공

---

# 📊 Baseline vs Proposed Method

| Process                | Baseline    | Proposed             |
| ---------------------- | ----------- | -------------------- |
| Claim Detection        | 숫자 포함 문장 추출 | 검증 가능한 주장 탐지 및 유형 분류 |
| Information Extraction | 수동 확인       | 자동 정보 추출             |
| Statistical Retrieval  | 수동 검색       | KOSIS API 기반 자동 검색   |
| Numerical Verification | 수작업 비교      | 자동 계산 및 검증           |
| Response Generation    | 없음          | 근거 기반 자연어 생성         |

---

# 🚀 Current Progress

* [x] 프로젝트 기획
* [x] 요구사항 분석
* [x] 시스템 설계
* [ ] Claim Detection 구현
* [ ] Information Extraction 구현
* [ ] KOSIS API 연동
* [ ] Numerical Verification 구현
* [ ] Chatbot 구현
* [ ] 성능 평가 및 개선

---

# 💡 Example

### Input

> "2024년 서울 청년 취업자는 전년보다 감소했다."

### Process

* Claim Detection
* Information Extraction
* KOSIS API Search
* Numerical Verification

### Output

```text
기사 주장:
2024년 서울 청년 취업자는 감소

KOSIS 조회 결과:
2023년 : XXXXX명
2024년 : XXXXX명

판정:
TRUE

근거:
KOSIS 공식 통계 기준 2024년 취업자 수가 2023년보다 감소함을 확인.
```

---

# 👥 Team

| Name | Role |
| ---- | ---- |
| 구정현 |      |
| 김진성 |      |
| 김은결 |      |
| 오가연 |      |

---

# ▶️ Getting Started

```bash
git clone https://github.com/rnwjdgus03/NLP_05-Team-Project-3.git

cd NLP_05-Team-Project-3

pip install -r requirements.txt
```

실행

```bash
uvicorn app:app --reload
```

---

# 📚 References

* KOSIS Open API
* Hugging Face Transformers
* Sentence Transformers
* FAISS
* FastAPI
* Pandas

---

# 📌 Project Status

현재 기업 요구사항을 기반으로 개발이 진행 중이며, 기능 구현 및 성능 검증을 순차적으로 진행하고 있습니다.
