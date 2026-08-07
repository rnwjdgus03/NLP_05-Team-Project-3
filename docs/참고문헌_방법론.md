# 참고문헌 및 대안 방법론 정리

- 작성: B팀, 2026-07-15
- 목적: 추출(①)·매칭(②) 단계의 대안 방법 탐색과 보고서·발표용 학술 근거 정리
- 우리 문제의 학술적 명칭: **statistical claim verification** (통계 주장 사실검증)

---

## 1. 전체 프레임 (보고서 서론·문제 정의용)

| 논문 | 내용 | 우리와의 관계 |
|---|---|---|
| Thorne et al., **FEVER: a Large-scale Dataset for Fact Extraction and VERification**, NAACL 2018 (arXiv:1803.05355) | claim → 증거 검색 → 판정 3단계 사실검증 파이프라인의 표준 벤치마크 | 우리 ①추출→②매칭→③검증 구조의 원형. 문제 정의 인용 |
| Karagiannis et al., **Scrutinizer: A Mixed-Initiative Approach to Large-Scale, Data-Driven Claim Verification**, PVLDB 2020 (arXiv:2003.06708) | 통계 claim을 통계 DB와 대조 검증. 지표·시점·축 추출 → DB 쿼리 변환 → 사람 검토 혼합. IMF와 실증 | **가장 직접적인 선행 연구.** 수동검토 큐·혼합 자동화까지 우리 운영 방식과 동일 |
| Vlachos & Riedel, **Identification and Verification of Simple Claims about Statistical Properties**, EMNLP 2015 | 통계적 속성 claim을 지식베이스 수치와 대조하는 태스크의 원조 | "뉴스 수치 주장 ↔ 공식 통계" 문제의 최초 정식화 |
| Jo et al. (Trummer), **Verifying Text Summaries of Relational Data Sets** (AggChecker), SIGMOD 2019 | 텍스트 요약문 주장을 관계형 DB 쿼리로 검증 | claim→쿼리 파라미터 변환 관점의 근거 |

**보고서 서술 예시**: FEVER의 3단계 프레임을 따르되, Scrutinizer처럼 통계 DB(KOSIS)를 검증 대상으로 하는 한국어 뉴스 도메인 적용이 본 프로젝트의 기여.

## 2. ① 추출 단계의 대안 방법

### 2-1. 시퀀스 라벨링 파인튜닝 (골드 300건+ 확보 후 권장)

- Park et al., **KLUE: Korean Language Understanding Evaluation**, NeurIPS 2021 Datasets — 한국어 NER·RE 벤치마크와 사전학습 모델(KLUE-RoBERTa)
- Devlin et al., **BERT**, NAACL 2019 / 박장원, **KoELECTRA** (2020, GitHub)
- 적용: 수치·단위·시점·대상 span을 BIO 태깅으로 추출. LLM 대비 추론 비용 0, 속도 수백 배. 골드가 쌓이면 "LLM vs 파인튜닝" ablation 실험 — 코랩 GPU 활용처
- 한계: 라벨 필요(현재 골드 63건으로는 부족), 정규화(2만867→20867)는 별도 후처리

### 2-2. 통합 구조화 생성 (UIE 계열)

- Lu et al., **Unified Structure Generation for Universal Information Extraction**, ACL 2022
- 적용: 추출을 스키마-유도 생성 문제로 정의. 소형 생성모델 파인튜닝 경로. LLM(HCX)과 파인튜닝의 중간 지점

### 2-3. 시점 정규화 전용 규칙 (하이브리드 근거)

- Strötgen & Gertz, **HeidelTime**, SemEval 2010 / Chang & Manning, **SUTime**, LREC 2012
- 적용: "지난 8월"→202508 상대시점 역산을 규칙 엔진으로. LLM period 오류가 잔존하면 이 계열로 해당 필드만 대체 검토

### 2-4. 게이트(검증가치 분류) 독립 태스크

- Hassan et al., **ClaimBuster: Detecting Check-worthy Factual Claims**, KDD 2017
- Barrón-Cedeño et al., **CLEF CheckThat! Lab** (2018~) — check-worthiness 공유 태스크
- 적용: verifiable_kosis 이진 분류기를 KLUE-RoBERTa로 파인튜닝하는 근거. 게이트만 따로 떼어 학습하는 것은 확립된 관행

## 3. ② 매칭 단계의 대안 방법

### 3-1. Entity Linking 프레임 — 현 설계의 학술 버전 (최우선 실험 권장)

- Wu et al., **Scalable Zero-shot Entity Linking with Dense Entity Retrieval** (BLINK), EMNLP 2020
- 구조: bi-encoder(임베딩)로 후보 top-k 검색 → cross-encoder(rerank)로 확정
- 대응: 지표 코드북 = alias table, 임베딩 후보 검색 + HCX rerank = BLINK 2단계. **이미 설계한 깔때기 1·2층이 이 논문 구조와 일치** — 구현 부담 최소로 학술 근거 확보

### 3-2. Dense Retrieval + Reranking

- Karpukhin et al., **Dense Passage Retrieval**, EMNLP 2020 — 임베딩 검색의 표준
- Chen et al., **BGE M3-Embedding**, 2024 (arXiv:2402.03216) — 다국어(한국어 포함) 임베딩 모델. 107,138개 표명 인덱싱에 사용
- Nogueira & Cho, **Passage Re-ranking with BERT**, 2019 (arXiv:1901.04085) — cross-encoder rerank
- Reimers & Gurevych, **Sentence-BERT**, EMNLP 2019 / Gao et al., **SimCSE**, EMNLP 2021 — 확정 매핑 쌍이 쌓이면 contrastive 파인튜닝(코랩 GPU)으로 검색기 개선

### 3-3. 테이블 검색·테이블 기반 검증

- Chen et al., **TabFact**, ICLR 2020 — 표 기반 사실검증 벤치마크
- Herzig et al., **Open Domain Question Answering over Tables via Dense Retrieval**, NAACL 2021 — 자연어로 "표를 찾는" 태스크의 직접 근거

### 3-4. Text-to-SQL의 Schema Linking 관점

- Yu et al., **Spider**, EMNLP 2018 / Wang et al., **RAT-SQL**, ACL 2020
- 대응: claim → (tbl_id, objL, itmId, prdSe) 변환은 자연어→쿼리 파라미터의 schema linking과 동형. 표별 축 사전(axis dictionary) 설계의 이론적 배경

## 4. 적용 로드맵 (실험 우선순위)

| 순위 | 실험 | 근거 논문 | 시점 |
|---|---|---|---|
| 1 | 임베딩(BGE-M3) 후보 검색 + HCX rerank (BLINK 구조) | BLINK, DPR, BGE-M3 | 지금 — 골드 불필요, 코랩 활용 |
| 2 | 표별 축 사전으로 objL/itmId 자동 해소 | RAT-SQL(schema linking) | 지금 — 메타 API 캐싱 |
| 3 | 게이트 이진 분류기 파인튜닝 | ClaimBuster, KLUE | 골드 300건+ |
| 4 | 추출 시퀀스 라벨링 vs LLM ablation | KLUE, UIE | 골드 300건+ |
| 5 | 확정 매핑 쌍 contrastive 검색기 파인튜닝 | SimCSE, Sentence-BERT | 확정 매핑 수백 건+ |

## 5. 평가 방법론 근거 (이미 실천 중인 것들)

- 골드셋·홀드아웃 분리, 코드북 동결 후 독립 평가 → 표준 train/dev/test 규율 (KLUE 등 모든 벤치마크 관행)
- "API 성공률 ≠ 의미 정확도" 구분 → FEVER의 evidence-aware 평가(맞는 근거로 맞춰야 인정)와 동일 사상
- hallucination guard(후보 목록 내 선택 강제 + 코드 재검증) → constrained decoding/grounded generation 계열의 실무 적용
