-- =========================================================
-- 회차 신청 (EXAM-03/04)
-- =========================================================
-- 신청 취소는 soft delete(deleted_at)로 처리한다. 같은 사람이 같은 회차에
-- "활성 신청"을 중복으로 가질 수는 없지만(부분 유니크 인덱스), 취소 후
-- 재신청은 새 행으로 허용한다 — 그래야 신청/취소 이력이 전부 남는다.

create table tb_exam_application (
  exam_application_id serial primary key,
  exam_id              integer not null references tb_exam (exam_id),
  user_id              integer not null references tb_user (user_id),
  applied_at           timestamptz not null default now(),
  created_at           timestamptz not null default now(),
  modified_at          timestamptz not null default now(),
  deleted_at           timestamptz
);

comment on table tb_exam_application is '회차 신청 — 응시자가 특정 시험 회차에 신청한 기록';
comment on column tb_exam_application.applied_at is '신청 시각';
comment on column tb_exam_application.deleted_at is '신청 취소 시각(soft delete). null이면 신청 유지 중';

-- 활성 신청(deleted_at is null) 기준으로만 (exam_id, user_id) 유니크 —
-- 취소 후 재신청 시 새 행을 허용하기 위해 전체 유니크가 아닌 부분 인덱스로 건다.
create unique index uq_exam_application_active_user_exam
  on tb_exam_application (exam_id, user_id)
  where deleted_at is null;

create index idx_exam_application_exam on tb_exam_application (exam_id) where deleted_at is null;

alter table tb_exam_application enable row level security;
