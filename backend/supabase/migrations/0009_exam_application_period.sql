-- =========================================================
-- 시험 회차 신청 기간(application_open_at/application_close_at) 추가
-- =========================================================
-- open_at/close_at은 "시험 응시 가능 기간"이고, 신청(EXAM-03/04)이 가능한
-- 기간은 별도다 — 응시 기간이 시작되기 전에 신청이 마감되는 것이 일반적인
-- 흐름이므로 두 기간을 완전히 분리한다.

alter table tb_exam
  add column application_open_at timestamptz not null default now(),
  add column application_close_at timestamptz not null default now();

alter table tb_exam
  alter column application_open_at drop default,
  alter column application_close_at drop default;

comment on column tb_exam.application_open_at is '신청 접수 시작 시각';
comment on column tb_exam.application_close_at is '신청 접수 마감 시각';
