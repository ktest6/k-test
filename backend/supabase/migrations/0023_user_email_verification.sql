-- =========================================================
-- 이메일 인증(코드 방식) 필드 추가
-- =========================================================
-- 가입 직후 6자리 인증번호를 메일로 보내고, 프론트가 같은 화면에서
-- 코드를 입력받아 확인한다. 코드는 만료시각을 두고, 틀린 시도 횟수를
-- 세어 무제한 추측을 막는다(별도 rate-limit 인프라가 없어서 컬럼으로 처리).

alter table tb_user
  add column email_verified_at             timestamptz,
  add column email_verification_code       varchar(6),
  add column email_verification_expires_at timestamptz,
  add column email_verification_attempts   integer not null default 0;

comment on column tb_user.email_verified_at is '이메일 인증 완료 시각. NULL이면 미인증.';
comment on column tb_user.email_verification_code is '발송된 6자리 인증번호. 인증 완료/재발송 시 새 값으로 대체.';
comment on column tb_user.email_verification_expires_at is '인증번호 만료 시각.';
comment on column tb_user.email_verification_attempts is '현재 발급된 코드에 대한 틀린 시도 횟수. 재발송 시 0으로 초기화.';
