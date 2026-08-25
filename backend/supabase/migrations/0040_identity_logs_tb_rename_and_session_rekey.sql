-- =========================================================
-- identity_logs → tb_identity_logs 이름 통일 + exam_session_id 재추가
-- =========================================================
-- 0039에서 (exam_id, user_id) → exam_session_id로 되돌리려 했으나 이 테이블에는
-- 실제로 적용되지 않았다(tb_exam_session.exam_id 컬럼 제거만 반영되고 나머지는
-- 누락된 상태로 확인됨). 그 사이 애플리케이션 코드는 이미 exam_session_id
-- 기준으로 인증 로그를 기록하도록 바뀌어 있어서, 이 테이블을 그대로 두면
-- INSERT 시 존재하지 않는 컬럼 참조로 매번 실패한다 — 이번 마이그레이션으로
-- 실제 반영한다.
--
-- 겸사겸사 다른 주 도메인 테이블(tb_user, tb_exam_session 등)과 같은 tb_ prefix
-- 네이밍으로 테이블명도 맞춘다(0035에서 gaze_calibrations/earphone_logs를 같은
-- 이유로 이미 rename한 전례를 따른다).
--
-- exam_id/user_id로 남아있던 기존 로그들은 어느 세션의 시도였는지 지금 매핑할
-- 방법이 없어(그 시절엔 세션보다 인증이 먼저 이루어지는 구조였다) exam_session_id를
-- NULL로 둔 채 보존한다 — 감사 이력으로서의 의미는 있지만 세션 단위 조회
-- 대상에서는 자연히 빠진다.

alter table identity_logs rename to tb_identity_logs;

drop index if exists idx_identity_logs_exam_user;

alter table tb_identity_logs
  drop constraint if exists identity_logs_exam_id_fkey,
  drop constraint if exists identity_logs_user_id_fkey,
  drop column if exists exam_id,
  drop column if exists user_id;

alter table tb_identity_logs
  add column exam_session_id integer references tb_exam_session (exam_session_id) on delete cascade;

comment on column tb_identity_logs.exam_session_id is
  '이 본인인증이 속한 응시 시도(세션). 같은 시험을 여러 번 볼 수 있어 회차가 아니라 '
  '세션 기준. 0039 이전(rename 전) 레코드는 NULL — 당시엔 (exam_id, user_id) 기준이라 '
  '세션에 매핑할 방법이 없다.';

create index idx_tb_identity_logs_session on tb_identity_logs (exam_session_id, created_at desc);
