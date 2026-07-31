-- =========================================================
-- 서류 업로드 → AI 문항 생성 (document 모듈)
-- =========================================================
-- QUESTION-00 이후 tb_question 설계가 다시 바뀐다.
-- - exam_id를 다시 추가한다(nullable) — 문항이 서류에서 먼저 만들어지고
--   회차 배정은 나중에 별도 기능으로 이뤄지기 때문.
-- - mode/version은 개별 문항이 아니라 "생성 배치"(문서) 단위 정보라
--   tb_document.metadata로 옮기고 tb_question에서는 제거한다.
-- - checklist_items(JSONB)는 채점 모듈에서 항목별 weight로 점수를
--   계산해야 해서 tb_question_checklist_item으로 정규화한다.

create type document_status as enum ('UPLOADED', 'PROCESSING', 'COMPLETED', 'FAILED');
create type question_status as enum ('UNUSED', 'USED');

create table tb_document (
  document_id    serial primary key,
  file_path      varchar(500) not null,
  file_name      varchar(255) not null,
  uploaded_by    integer references tb_admin (admin_id),
  status         document_status not null default 'UPLOADED',
  metadata       jsonb,
  error_message  text,
  created_at     timestamptz not null default now(),
  modified_at    timestamptz not null default now()
);

comment on table tb_document is '관리자가 업로드한 문제 원본 자료 — AI가 이 서류로 문항 초안을 생성한다';
comment on column tb_document.file_path is 'Supabase Storage 경로 (프론트가 직접 업로드하고 경로만 전달)';
comment on column tb_document.uploaded_by is '업로드한 관리자(tb_admin). 시스템이 생성한 경우 등은 NULL 허용';
comment on column tb_document.metadata is '문항 생성 배치 단위 정보 (version, mode, note 등)';
comment on column tb_document.error_message is '생성 실패 시 에러 메시지 (status=FAILED일 때만 값 있음)';

create index idx_document_status on tb_document (status);

alter table tb_document enable row level security;

-- tb_question: exam_id/document_id/status 추가.
alter table tb_question
  add column exam_id integer references tb_exam (exam_id),
  add column document_id integer references tb_document (document_id),
  add column status question_status not null default 'UNUSED';

comment on column tb_question.exam_id is 'NULL이면 아직 회차 미배정. 생성 시점엔 항상 NULL, 배정 기능에서 채움';
comment on column tb_question.document_id is '이 문항을 생성한 서류. 서류 없이 만들어졌으면 NULL';
comment on column tb_question.status is '이 문항이 실제 회차에 쓰였는지(UNUSED/USED)';

-- ---- 기존 QUESTION-00 고정 세트(writing_v0)를 새 구조로 이관 ----
-- 1) 그 배치를 나타내는 tb_document를 하나 만든다 (실제 업로드 파일은 없었던
--    수동 시드라 file_path/file_name은 그 사실을 알 수 있는 placeholder로 채운다).
insert into tb_document (file_path, file_name, uploaded_by, status, metadata)
select
  'legacy/writing_v0_manual_seed',
  'writing_v0_manual_seed.json',
  (select admin_id from tb_admin order by admin_id limit 1),
  'COMPLETED',
  jsonb_build_object(
    'version', 'writing_v0',
    'mode', 'writing',
    'note', '2026-07-30 검수 완료. WRT-002 c4(높임)는 과제 완수의 일부로 보고 유지 결정.'
  )
where exists (select 1 from tb_question where mode = 'writing' and version = 'writing_v0');

-- 2) 그 배치로 만들어진 기존 문항에 document_id를 채운다.
update tb_question q
set document_id = d.document_id
from tb_document d
where d.file_path = 'legacy/writing_v0_manual_seed'
  and q.mode = 'writing'
  and q.version = 'writing_v0';

-- 3) 정규화된 체크리스트 테이블을 만들고, 기존 checklist_items(JSONB)를 옮긴다.
create table tb_question_checklist_item (
  checklist_item_id  serial primary key,
  question_id        integer not null references tb_question (question_id),
  code                varchar(10) not null,
  description         varchar(500) not null,
  weight              numeric(4, 2) not null,
  display_order       integer not null,
  created_at          timestamptz not null default now(),
  modified_at         timestamptz not null default now(),
  deleted_at          timestamptz
);

comment on table tb_question_checklist_item is '문항별 채점 체크리스트 항목';

insert into tb_question_checklist_item (question_id, code, description, weight, display_order)
select
  q.question_id,
  item ->> 'id',
  item ->> 'description',
  (item ->> 'weight')::numeric,
  (ord - 1)::integer
from tb_question q
cross join lateral jsonb_array_elements(q.checklist_items) with ordinality as t (item, ord)
where q.checklist_items is not null;

-- 4) 이관이 끝났으니 예전 컬럼을 정리한다.
alter table tb_question
  drop column checklist_items,
  drop column mode,
  drop column version;
