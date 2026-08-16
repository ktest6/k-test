-- =========================================================
-- 여권번호 처리 동의(필수) 추가, 선택 동의 항목을 실제 확정된 내용으로 수정
-- =========================================================
-- 실제 확정된 약관 항목은 4개(필수 3 + 선택 1)였다:
--   1. K-TEST 서비스 이용약관 (필수) — terms_agreed_at
--   2. 개인정보 수집·이용 및 국외이전 동의서 (필수) — privacy_agreed_at
--   3. 여권번호 처리 동의 (필수) — 신규, passport_processing_agreed_at
--   4. 음성 데이터의 AI 모델 학습 활용 동의 (선택) — marketing_agreed_at을
--      이 용도로 재사용(컬럼명 변경). 0025에서 "마케팅 정보 수신 동의"로
--      가정해서 만들었던 게 실제로는 이거였다 — 그 마이그레이션에 남긴 메모
--      그대로, 아직 실 데이터가 없어(있어도 데모 계정뿐) 컬럼명만 바꾼다.

alter table tb_user
  add column passport_processing_agreed_at timestamptz;

comment on column tb_user.passport_processing_agreed_at is
  '여권번호 처리 동의 시각(필수, 회원가입 시 기록 — true 강제는 애플리케이션 레벨). 기존 계정은 NULL일 수 있음.';

alter table tb_user
  rename column marketing_agreed_at to voice_data_ai_training_agreed_at;

comment on column tb_user.voice_data_ai_training_agreed_at is
  '음성 데이터의 AI 모델 학습 활용 동의 시각(선택). 동의 안 했으면 NULL.';
