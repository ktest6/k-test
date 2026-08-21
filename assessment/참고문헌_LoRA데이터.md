# 참고문헌 — LoRA 데이터 보강 설계 (2026-08-19 조사분)

> 쓰는 법: 보고서에 인용할 때 이 파일에서 복사한다. 모든 항목은 검증 에이전트가 **원문(논문 본문·코드·공식 페이지)을 실제로 열람해 대조**한 것이다.
> - `[확정]` = 제목·수치까지 원문에서 확인됨 → 수치 인용 가능
> - `[실재]` = 출처는 실재하나 세부 수치는 미확인 → **수치 인용 금지**, "이런 접근이 있다"까지만
> - ⚠ 표시 = 2026년 프리프린트(동료검토 전) → "프리프린트"라고 밝히고 인용

---

## C 갈래 — 학습 목표·라벨 교정 (우리 병목에 정면 대응)

### 라벨 충실도·verbatim 전사

- `[확정]` **Acoustically Precise Hesitation Tagging Is Essential for End-to-End Verbatim Transcription Systems** (2025) — Whisper LoRA + L2 학습자(우리와 같은 세팅)에서 라벨 표기 충실도만 고쳐 WER 6.2%→5.5%(상대 11.3% 개선). Gemini 2.0 Flash로 정밀 라벨 제작. https://arxiv.org/abs/2506.04076
- `[확정]` ⚠ **Transcription Policy as a Latent Variable: Activating Controllable Verbatim ASR** (nyra labs/CrisperWhisper 팀, 2026) — 전사 스타일(들린 대로 vs 고쳐 적기)은 통제 안 된 잠재 변수(스타일 불일치가 보고 WER의 최대 60%). 디코더 앞 스타일 태그 임베딩 27개만 1에폭 학습해도 비유창성 F1 10%→79%, 디코더까지 풀면 90.7%. verbatim 학습 데이터 약 362시간. https://arxiv.org/abs/2607.18934
- `[확정]` **CrisperWhisper: Accurate Timestamps on Verbatim Speech Transcriptions** (Interspeech 2024) — Whisper large-v3를 verbatim 전사로 파인튜닝, AMI WER 8.72 vs 원본 16.01. verbatim 전사 공개 모델의 존재 증명. https://arxiv.org/abs/2408.16589
- `[확정]` **Prompting Whisper for Improved Verbatim Transcription and End-to-end Miscue Detection** (Apple, Interspeech 2025) — 낭독 지문을 디코더 프롬프트로 주는 것이 파인튜닝보다 verbatim 전사에 유리. (A 갈래의 직접 근거) https://arxiv.org/abs/2505.23627
- `[확정]` ⚠ **Subtitle-Aligned Fine-Tuning of Whisper for Swiss German ASR** (2026, 단독 저자 프리프린트) — 라벨이 표준어로 번역된 코퍼스에서는 모델이 언어가 아니라 "표기 관습"을 학습함을 고발. 내용 오류(cWER)와 스타일 차이(sWER) 분리 지표 제안. Whisper LoRA에서 α/r≈0.2 권장(통상 α=2r 반박). https://arxiv.org/html/2606.07608v1

### 의사라벨·합의 필터 (재라벨 공장)

- `[확정]` **Distil-Whisper: Robust Knowledge Distillation via Large-Scale Pseudo Labelling** (2023) — 의사라벨 21,170시간 중 WER>10% 샘플 제거(45.4%)로 평균 WER 13.4→11.4. 10% 문턱이 균형점(본문 Table 10). https://arxiv.org/abs/2311.00430
- `[확정]` **uDistil-Whisper: Label-Free Data Filtering for Knowledge Distillation in Low-Data Regimes** (NAACL 2025 본회의) — 정답 라벨 없이 의사라벨 필터링이 성립, 증류 모델이 교사보다 5~7 WER 포인트 우위. "사람 라벨을 못 믿는 상황"의 정당화 근거. https://arxiv.org/abs/2407.01257
- `[확정]` **Efficient Data Selection for Domain Adaptation of ASR Using Pseudo-Labels and Multi-Stage Filtering** (Interspeech 2025) — ASR 3종의 쌍별 CER 합의 필터로 7,500시간→100시간(1.4%)으로 줄여도 전체 학습과 동급(12.2% vs 12.3% WER). 합의 문턱 CER<5%. https://arxiv.org/abs/2506.03681
- `[확정]` **Better Pseudo-labeling with Multi-ASR Fusion and Error Correction by SpeechLLM** (Interspeech 2025) — 다중 ASR 출력의 단어 단위 다수결 + LLM 중재로 의사라벨 정확도 개선. (동률 시 "선택만" 중재의 근거) https://arxiv.org/abs/2506.11089
- `[확정]` **From Weak Labels to Strong Results: 5,000 Hours of Noisy Classroom Transcripts** (2025) — 부정확 라벨 대량으로 먼저 학습 → 소량 정확 라벨로 마무리(WSP 2단계)가 대안들을 능가. https://arxiv.org/abs/2505.17088
- `[확정]` **Improved Noisy Student Training for Automatic Speech Recognition** (2020) — 준지도 학습 고전. 의사라벨은 반복마다 "필터링·균형화·증강"이 핵심. LibriSpeech 100h+860h로 WER 4.2%/8.6%. https://arxiv.org/abs/2005.09629
- `[확정]` **slimIPL: Language-Model-Free Iterative Pseudo-Labeling** (2021) — LM 없이 하드 라벨 반복 재생성, 라벨 10시간만으로도 경쟁력. https://arxiv.org/abs/2010.11524
- `[확정]` **Improving Noisy Student Training on Non-target Domain Data for ASR** (2022) — 두 디코딩 결과의 차이를 신뢰도 필터로 사용(LM Filter), 무필터 대비 10.4% 개선. https://arxiv.org/abs/2211.04717
- `[확정]` **Investigation of Training Label Error Impact on RNN-T** (2021) — 라벨 오류 중 삭제가 가장 해롭고, 완화 트릭으로는 격차를 못 없앤다 → 라벨 품질 확보가 정공법. https://arxiv.org/abs/2112.00350
- `[실재]` ⚠ **Mispronunciation Detection and Diagnosis for Non-Native Korean Learners Using Iterative Pseudo-Label Refinement** (Applied Sciences 16(5):2426, 2026-03-02 게재) — 비원어민 한국어 + 교차모델 합의 + 다단계 의사라벨 정제 = 우리와 가장 가까운 선행. 본문 접근 차단으로 수치 미확인 — **PDF 확보 전 수치 인용 금지.** https://www.mdpi.com/2076-3417/16/5/2426
- `[확정]` **Self-supervised learning-based Korean phoneme recognition for evaluating Korean pronunciation of non-native speakers** (말소리와 음성과학 17(1), 2025, HUFS) — AI Hub 교육용 데이터 + G2P 발음 표기 라벨로 비원어민 PER 12.50%→3.22%. "발음 기반 표기가 문맥 의존을 줄인다" 명시. https://www.eksss.org/archive/view_article?pid=pss-17-1-51

### 손실·선호최적화·LoRA 설계

- `[확정]` **Token-Weighted RNN-T for Learning from Flawed Data** (2024) — 라벨 신뢰도를 토큰 단위 손실 가중으로 반영, 의사라벨 학습 최대 38% 상대 개선, 주석 오류 손실 64~99% 회복. (단, RNN-T 기준 — seq2seq 이식은 우리 검증 몫) https://arxiv.org/abs/2406.18108
- `[확정]` ⚠ **Direct Preference Optimization for English-Mandarin Code-Switching Speech Recognition in Audio LLMs** (2026) — chosen=원발화 보존, rejected=LLM이 정규화(번역)한 전사(전체 80%+부분 20%)로 DPO 1에폭 → MER 70.98%→7.38%. "정규화 전사를 지는 답으로" 구조의 실증. https://arxiv.org/abs/2605.23975
- `[확정]` **Enhancing Audiovisual Speech Recognition through Bifocal Preference Optimization** (AAAI 2025) — seq2seq ASR(OWSM)에 선호최적화 적용, SFT 대비 상대 11.4% 개선. rejected는 ChatGPT 3전략 생성. https://arxiv.org/abs/2412.19005
- `[확정]` **QLoRA: Efficient Finetuning of Quantized LLMs** (NeurIPS 2023) — LoRA는 어텐션+MLP 전 선형층에 걸어야 full FT 동급, rank보다 어댑터 커버리지가 중요. https://arxiv.org/abs/2305.14314
- `[확정]` **Sparsely Shared LoRA on Whisper for Child Speech Recognition** (ICASSP 2024) — 아동 음성(비전형 화자)에서 full FT(CER 19.86%)보다 LoRA 계열(8.67%)이 우위 — 소량 데이터에서 full FT 위험의 방증. https://arxiv.org/abs/2309.11756
- `[확정]` ⚠ **Do LLM Decoders Listen Fairly? Benchmarking How Language Model Priors Shape Bias in Speech Recognition** (2026) — Whisper는 클수록 비표준 억양에서 삽입·반복 폭주 심화(large-v3 삽입률이 medium의 6.3배). small 유지의 방어 논리. https://arxiv.org/html/2604.21276v1
- `[확정]` ⚠ **Whisper Hallucination Detection and Mitigation via Hidden Representation Steering and Sparse AutoEncoders** (2026) — 환각 정보는 인코더 깊은 층에서 선형 분리 가능, 스티어링으로 환각률 72.63%→14.11%(small). (간접 근거) https://arxiv.org/abs/2606.07473
- `[확정]` **WhisTLE: Deeply Supervised, Text-Only Domain Adaptation for Pretrained Speech Recognition Transformers** (2025) — 텍스트만으로 디코더 도메인 적응, TTS 병용 시 평균 상대 WER 49.0% 감소(112개 시나리오 중 100개 승). https://arxiv.org/abs/2509.10452

---

## B 갈래 — 실데이터 확보 (전부 공식 페이지에서 확인)

- `[확정]` **AI Hub 교육용 영어 모국어 사용자의 한국어 음성 데이터** (dataSetSn=71469, 2022) — 1,029.8시간. 발음오류 보존 수동 발음전사 + 발음숙련도·유창성·이해가능도(1~5점) + 말하기 평가(전달력·언어사용·내용) 라벨. https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71469
- `[확정]` **AI Hub 교육용 유럽어 모국어 사용자의 한국어 음성 데이터** (dataSetSn=71489, 2022) — 1,538.5시간. 같은 라벨 구성. https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71489
- `[확정]` **AI Hub 교육용 중·일어 모국어 사용자의 한국어 음성 데이터** (dataSetSn=71490, 2022) — 1,006.2시간. 같은 라벨 구성 + 발음오류 태깅(TextGrid). https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71490
- `[확정]` **AI Hub 교육용 아시아어(중·일어 제외) 사용자의 한국어 음성 데이터** (dataSetSn=71479, 2022) — 우리가 쓰는 원천. 원본 전체 1,500시간(우리 학습쌍 10,151개는 샘플판 일부). 발음 문항 음소열 전사 + 평가점수 라벨 포함(페이지 표기). ※ 8/19 로컬 실측: 샘플 zip 라벨마다 전달력·언어사용·내용 0~5점 실재 확인, 발음전사는 샘플엔 없어 전체판에서 확인 필요. https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=71479
- `[확정]` **AI Hub 인공지능 학습을 위한 외국인 한국어 발화 음성 데이터** (dataSetSn=505, 2021) — 4,302시간, 화자 1,911명·80개 L1(논문 기준). 오류 보존 전사 여부 미명시 → 샘플 실측 게이트 필요. https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=505
- `[확정]` **국립국어원 한국어 학습자 말뭉치 나눔터** — 10년 구축, 총 1,588만 어절(2025-08 보도), 오류 주석 말뭉치 포함. 단 "학습자 원본 자료(음성) 미제공" 명시 → STT 학습 불가, 오류 주석 텍스트만 활용. https://kcorpus.korean.go.kr
- `[확정]` **Comparison of L2 Korean pronunciation error patterns from five L1 backgrounds by using automatic phonetic transcription** (ICPhS 2023) — AI Hub 505 데이터로 5개 L1 분석, 자동 음소전사 PER 3.88%, 840개 패턴 중 L1 연관 39종(격음·경음→평음, 종성 탈락, 이중모음 단모음화, 베트남어 /l/→/n/). D 갈래 규칙표의 원천이기도 함. https://arxiv.org/abs/2306.10821
- `[확정]` **Common Voice 한국어** — 검증분 2.54시간·화자 210명뿐(26.0 릴리스 직접 파싱) → 데이터 소스로 부적합 판정. (조사 초안의 375시간은 36배 과대로 판명·폐기 — 정직 기록) https://github.com/common-voice/cv-dataset

---

## D 갈래 — 합성 데이터 (오류 주입 텍스트 → TTS)

### 오류 텍스트 생성 (GEC·오류 주입)

- `[확정]` **Synthetic Data Generation for Grammatical Error Correction with Tagged Corruption Models** (Google, BEA 2021) — 오류 유형 태그 + 실측 분포로 조건화한 오염이 무작위 오염을 일관되게 이김. C4_200M(2억 문장) 공개. https://arxiv.org/abs/2105.13318
- `[확정]` **To Err Is Human, but Llamas Can Learn It Too** (EMNLP 2024 Findings) — LLM을 "교정의 역방향"(정문→오류문)으로 써서 독일어·우크라이나어·에스토니아어 GEC F0.5 0.8~6점 향상. 프롬프트만으로도 유효. https://arxiv.org/abs/2403.05493
- `[확정]` **An Empirical Study of Incorporating Pseudo Data into Grammatical Error Correction** (EMNLP 2019) — 합성으로 먼저 사전학습 → 실데이터로 마무리(PRETRAIN)가 혼합 일괄학습(JOINT)보다 우위. https://arxiv.org/abs/1909.00502
- `[확정]` **Enhancing Arabic Automated Essay Scoring with Synthetic Data and Error Injection** (BEA 2025) — GPT-4o에 [오류 태그 13종 정의 + 수준별 실측 분포 + 태그별 예시] 3종 세트로 채점용 합성 에세이 3,040편 제작. 우리와 가장 닮은 최신 사례(비영어·채점 목적). https://arxiv.org/abs/2503.17739
- `[확정]` **Towards standardizing Korean Grammatical Error Correction: Datasets and Annotation** (ACL 2023) — 한국어 오류 유형 14종 자동 주석 도구 KAGAS + Kor-Learner 등 3개 데이터셋 공개. https://arxiv.org/abs/2210.14389
- `[확정]` **K-NCT: Korean Neural Grammatical Error Correction Gold-Standard Test Set** (IEEE Access, 2022) — 한국어 오류 대분류 4종·하위 23종 분류 기준 + 3,000문장. 오류 태그 체계의 표준 출처. https://ieeexplore.ieee.org/document/9938990/
- `[실재]` **베트남인 한국어 학습자의 종성 유음 /ㄹ/ 발음 오류 분석** (우리말연구 64호, 2021) — /ㄹ/ 오류율 초급 81%·중급 68.2%·고급 27.6% (KCI 초록 확인). 급수별 주입 확률의 근거. ※"ㄱㄷㄹㅂ 탈락 우세" 등 일반화는 원출처 별도 확보 전 인용 금지. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002682458
- `[확정]` **Automated detection of pronunciation errors in non-native English speech employing deep learning** (Korzekwa 박사논문, 2022) — 오류 "탐지"를 "합성 오류 발화 생성"으로 뒤집어 AUC 0.528→0.749(41% 개선). T2S(오류 텍스트를 TTS로 낭독) 방식의 원조. https://arxiv.org/abs/2209.06265 (요약판: Speech Communication, https://arxiv.org/abs/2207.00774)
- `[확정]` **L2-GEN: A Neural Phoneme Paraphrasing Approach to L2 Speech Synthesis for Mispronunciation Diagnosis** (Amazon, Interspeech 2022) — 실제 L2 분포를 흉내 낸 오류 음소열 합성으로 MDD F1 인도메인 +3.9%, 아웃도메인 +5.0%. https://www.isca-archive.org/interspeech_2022/zhang22_interspeech.html
- `[확정]` **SpeechBlender: Speech Augmentation Framework for Mispronunciation Data Generation** (2023) — TTS 없이 실오디오 음소 블렌딩으로 발음오류 데이터 생성(CPU 대안). https://arxiv.org/abs/2211.00923
- `[확정]` ⚠ **Few-Shot Synthetic Accented Speech for ASR Fine-Tuning: What Helps and When?** (2026) — 합성 단독 파인튜닝(WER 33.8%)은 실발화(14.1%)보다 크게 나쁨. 무작위 음소 치환만으로 LLM 정교 편집 이득 대부분 회수. ※한국인 억양 "영어" 실험 — 도메인 차이 단서 필수. https://arxiv.org/abs/2604.27273

### TTS→ASR 증강 방법론

- `[확정]` **Generating Synthetic Audio Data for Attention-Based Speech Recognition Systems** (RWTH Aachen, 2019) — 이 갈래의 고전. 저자원에서 합성음 혼합으로 상대 WER 최대 33% 개선. https://arxiv.org/abs/1912.09257
- `[확정]` **Text Generation with Speech Synthesis for ASR Data Augmentation** (Meta, Interspeech 2023) — 혼합 비율 실측: 넓은 도메인 50%까지, 특정 도메인은 10% 이하가 최적. 속도 3종·노이즈 60% 증강 레시피. https://arxiv.org/abs/2305.16333
- `[확정]` **SYNT++: Utilizing Imperfect Synthetic Data to Improve Speech Recognition** (Apple, ICASSP 2022) — 합성음은 필터 없이 넣으면 손해. 거부 샘플링 + 통계 분리로 WER 7.7%→4.0%. https://arxiv.org/abs/2110.11479
- `[확정]` **An Exhaustive Evaluation of TTS- and VC-based Data Augmentation for ASR** (2025) — 피치·화자 단독 증강은 무효, 여러 속성 동시 증강이 유효(최대 상대 35%). https://arxiv.org/abs/2503.08954
- `[확정]` **A Self-Refining Framework for Enhancing ASR Using TTS-Synthesized Data** (Twister, 2025) — Whisper에 TTS 합성쌍 재주입이 대규모로 작동(만다린 오류율 최대 20%↓). https://arxiv.org/abs/2506.11130
- `[확정]` **When Whisper Meets TTS: Domain Adaptation Using only Synthetic Speech Data** (TSD 2023) — 합성음만으로 Whisper 디코더 적응, 저자원 언어 WER 2~30포인트 개선. https://link.springer.com/chapter/10.1007/978-3-031-40498-6_20
- `[확정]` **Zero Shot Text to Speech Augmentation for ASR on Low-Resource Accented Speech Corpora** (2024) — 합성 단독 최대 5% WERR vs 실데이터 소량+합성 혼합 최대 14% WERR → "혼합이 답". https://arxiv.org/abs/2409.11107
- `[실재]` **Bridging the Language Gap: Synthetic Voice Diversity via Latent Mixup** (ICML 2025 Workshop) — 합성 화자 다양성이 관건이라는 방증(수치는 원문 재확인 전 인용 금지). https://arxiv.org/abs/2511.20534

### TTS 도구 (코드·라이선스 직접 확인)

- `[확정]` **CosyVoice2-0.5B** (Alibaba FunAudioLLM) — 한국어 포함 9개 언어 zero-shot 음성복제, Apache-2.0. frontend.py에 한글 철자 교정 경로 없음(코드 열람) — 오류 표기가 보존됨. ※숫자는 영어로 풀릴 위험. https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B
- `[확정]` **GPT-SoVITS v2** — MIT, 한국어 지원(2024-08). korean.py는 g2pk2 표면형 발음규칙만 적용(교정 단계 부재, 코드 열람). 화자별 1분 파인튜닝. RTF 0.014(4090). https://github.com/RVC-Boss/GPT-SoVITS
- `[확정]` **g2pK** — 표면형에 표준 발음규칙만 적용, 철자 교정 기능 없음(README 확인). 기대 발음열 생성 + 발음 채점 대체안에도 사용. https://github.com/kyubyong/g2pK
- `[확정]` **XTTS-v2 — 배제**: 가중치 CPML(비상업) + Coqui 폐업(2024-01)으로 상용 라이선스 구매 불가. https://huggingface.co/coqui/XTTS-v2
- `[확정]` **Fish-Speech/OpenAudio — 배제**: 라이선스가 "자료를 다른 AI 모델 학습에 사용" 자체를 금지(LICENSE 직접 열람) — TTS 출력으로 ASR 학습하는 우리 용도와 정면 충돌. https://github.com/fishaudio/fish-speech
- `[확정]` **MeloTTS + OpenVoice V2** (MyShell) — 둘 다 MIT·한국어. MeloTTS는 고정 화자(복제 없음), OpenVoice V2와 조합 시 음색 복제. https://github.com/myshell-ai/OpenVoice
- `[확정]` **ElevenLabs API** — 한국어 지원(multilingual v2), $0.10/1천자, `apply_text_normalization=off` 파라미터 존재. ※합성물로 타사 모델 학습이 약관상 허용되는지 미확인 — 사용 전 ToS 확인. https://elevenlabs.io/docs/api-reference/text-to-speech/convert

---

## 인용할 때 지킬 것 (수상 레시피 정합)

1. `[실재]` 항목은 수치를 절대 인용하지 않는다 — "같은 접근의 선행이 있다"까지만.
2. ⚠ 프리프린트는 "동료검토 전"임을 밝힌다. 특히 2606.07608은 단독 저자라 "독립 재현 사례" 수준으로만.
3. 타 언어·타 과제 수치(영어 GEC, 억양 영어 ASR 등)는 반드시 과제·언어를 병기한다 — "한국어에서 이만큼 된다"로 읽히게 쓰지 않는다.
4. "철자 수준 오류 보존 한국어 STT"를 그대로 다룬 선행은 조사 범위에서 미발견 — 이것은 한계이자 우리 신규성 주장의 근거(주장은 "조사 범위에서"까지만).
