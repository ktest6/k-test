-- 본인인증이 시험 세션 생성보다 먼저 이루어져야 하므로, identity_logs를
-- tb_exam_session이 아니라 (exam_id, user_id)에 직접 연결한다.
alter table identity_logs
  drop constraint identity_logs_exam_session_id_fkey,
  drop column exam_session_id;

alter table identity_logs
  add column exam_id integer not null references tb_exam (exam_id) on delete cascade,
  add column user_id integer not null references tb_user (user_id) on delete cascade;

drop index if exists idx_identity_logs_session;
create index idx_identity_logs_exam_user on identity_logs (exam_id, user_id, created_at desc);
