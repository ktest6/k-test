-- =========================================================
-- 문항-회차 배정을 다대다로 전환 (tb_exam_question)
-- =========================================================
-- 문항 하나가 여러 회차에 재사용될 수 있어서(예: 1회차에 냈던 문항을
-- 몇 달 뒤 2회차에도 또 낼 수 있음), tb_question.exam_id 같은 1:1 FK로는
-- 표현이 안 된다. 회차-문항 배정을 별도 조인 테이블로 분리한다.
--
-- status(UNUSED/USED)도 같은 이유로 제거한다 — "배정 여부"는 이제
-- tb_exam_question에 활성 행이 있는지로 판단한다. 검토/발행 단계
-- (DRAFT/PUBLISHED 등)는 지금 범위 밖 — 생성되면 바로 배정 가능하게 간다.
--
-- 문항 내용을 고치고 싶으면 기존 행을 수정하지 않고 새 문항을 만든다
-- (tb_question은 append-only, 수정 API 없음) — 그래야 이미 배정된
-- 회차의 과거 출제 내용이 나중에 안 바뀐다.

alter table tb_question
  drop column exam_id,
  drop column status;

drop type if exists question_status;

create table tb_exam_question (
  exam_question_id  serial primary key,
  exam_id           integer not null references tb_exam (exam_id),
  question_id       integer not null references tb_question (question_id),
  assigned_by       integer references tb_admin (admin_id),
  created_at        timestamptz not null default now(),
  deleted_at        timestamptz
);

comment on table tb_exam_question is '회차별 문항 배정 — 문항 하나가 여러 회차에 재사용될 수 있어 다대다로 관리한다';
comment on column tb_exam_question.assigned_by is '배정한 관리자. 시스템이 배정한 경우 등은 NULL 허용';
comment on column tb_exam_question.deleted_at is '배정 해제 시각(soft delete) — 재배정 가능하도록 이력만 남기고 유니크 제약에서는 제외';

create unique index uq_exam_question_active on tb_exam_question (exam_id, question_id) where deleted_at is null;
create index idx_exam_question_exam on tb_exam_question (exam_id) where deleted_at is null;

alter table tb_exam_question enable row level security;
