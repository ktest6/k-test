-- 응시자가 명시적으로 "건너뛰기"를 선택한 문항을 기록한다. tb_answers와 달리
-- 채점 파이프라인(answer.saved 이벤트)과는 아예 접점이 없다 — 스킵한 문항은
-- 답안이 없으므로 채점 대상이 아니다. 이 테이블의 목적은 "이 문항은 처리됐다
-- (답했거나 건너뛰었거나)"를 판정해서, 마지막 문항까지 처리됐을 때 최종
-- 리포트(/finalize) 제출을 트리거하기 위함이다.
create table tb_skipped_questions (
  id uuid primary key default gen_random_uuid(),
  exam_session_id integer not null references tb_exam_session (exam_session_id) on delete cascade,
  question_id integer not null references tb_question (question_id) on delete cascade,
  skipped_at timestamptz not null default now()
);
comment on table tb_skipped_questions is '응시자가 명시적으로 건너뛴 문항 — 답안 없이도 "처리 완료"로 집계하기 위함(마지막 문항 판정/최종 리포트 제출 트리거용).';

create unique index uq_skipped_questions_session_question
  on tb_skipped_questions (exam_session_id, question_id);

alter table tb_skipped_questions enable row level security;
