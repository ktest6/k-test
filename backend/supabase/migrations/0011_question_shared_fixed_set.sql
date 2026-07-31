-- =========================================================
-- tb_question: 회차 무관 고정 문항 세트로 전환
-- =========================================================
-- 문항을 회차마다 새로 만드는 게 아니라 고정된 세트를 그대로 쓰고, 응시자에게
-- 보여줄 때도 순서를 랜덤으로 섞기로 했다. 그 결과 두 컬럼이 의미를 잃는다:
-- - exam_id: 문항이 특정 회차에 속할 필요가 없어졌다.
-- - question_no: "회차별 몇 번째 문항"이라는 의미가 없어졌고, 문항 구분은
--   question_id(PK)와 content.item_id로 충분하다.
-- 나중에 회차 전용 문항이 다시 필요해지면 그때 컬럼을 다시 추가한다.
--
-- 대신 mode(쓰기/말하기 등 대분류)와 version(그 모드의 확정 배치 버전, 예:
-- writing_v0)을 추가한다. JSONB(content) 안에 묻어두면 필터링할 때마다
-- content->>'version' 같은 JSON 연산자를 써야 해서 불편하므로 컬럼으로 뺀다.

alter table tb_question
  drop column exam_id,
  drop column question_no,
  add column mode varchar(50) not null default '',
  add column version varchar(50) not null default '';

alter table tb_question
  alter column mode drop default,
  alter column version drop default;

comment on column tb_question.mode is '문항 대분류 (writing, speaking 등)';
comment on column tb_question.version is '그 mode의 확정 배치 버전 (예: writing_v0)';
comment on column tb_question.part is '문항 세부 유형 (mode=writing이면 work_log/messenger_report 등)';
