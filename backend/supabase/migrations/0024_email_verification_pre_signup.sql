-- =========================================================
-- 이메일 인증을 가입 "전" 단계로 옮기기
-- =========================================================
-- 프론트 흐름이 [이메일 입력 → 인증코드 확인 → 나머지 정보 입력 → 최종 가입]
-- 순서로 바뀌면서, 코드 확인 시점엔 아직 tb_user row가 없다. 그래서 인증
-- 상태를 tb_user가 아니라 이메일 기준의 별도 테이블에 임시로 들고 있다가,
-- 가입이 완료되면 그 행은 지운다(consumeVerification).
--
-- tb_user.email_verification_code/expires_at/attempts는 이제 안 쓰므로 정리.
-- email_verified_at은 계속 남긴다 — 가입 시점에 이미 인증된 시각을 그대로 기록.

alter table tb_user
  drop column email_verification_code,
  drop column email_verification_expires_at,
  drop column email_verification_attempts;

create table tb_email_verification (
  email           varchar(255) primary key,
  code            varchar(6) not null,
  code_expires_at timestamptz not null,
  attempts        integer not null default 0,
  verified_at     timestamptz,
  created_at      timestamptz not null default now()
);

comment on table tb_email_verification is '가입 전 이메일 인증 대기 상태. 가입 완료 시 해당 행은 삭제된다.';

alter table tb_email_verification enable row level security;
create policy deny_anon_authenticated on tb_email_verification for all to anon, authenticated using (false) with check (false);
