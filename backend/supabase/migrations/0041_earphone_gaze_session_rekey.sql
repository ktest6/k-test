-- =========================================================
-- tb_earphone_logs, tb_gaze_calibrations를 exam_session_id 기준으로 재키잉
-- =========================================================
-- tb_identity_logs와 같은 이유(0040 참고) — 0039에서 의도했던 (exam_id, user_id)
-- → exam_session_id 전환이 이 두 테이블에도 실제로는 반영되지 않았다. 같은
-- 시험을 여러 번 볼 수 있게 되면서 exam_id만으로는 어느 응시 시도의 기록인지
-- 구분이 안 되고, 애플리케이션 코드는 이미 exam_session_id로만 기록/조회하도록
-- 바뀌어 있어 이대로 두면 매 요청이 존재하지 않는 컬럼 참조로 실패한다.
--
-- 두 테이블 다 exam_id/user_id로 남아있던 기존 로그는 세션 매핑 정보가 없어
-- exam_session_id를 NULL로 둔 채 보존한다(0040의 tb_identity_logs와 동일 처리).

-- ── tb_earphone_logs ──
drop index if exists idx_tb_earphone_logs_exam_user;

alter table tb_earphone_logs
  drop constraint if exists earphone_logs_exam_id_fkey,
  drop constraint if exists earphone_logs_user_id_fkey,
  drop column if exists exam_id,
  drop column if exists user_id;

alter table tb_earphone_logs
  add column exam_session_id integer references tb_exam_session (exam_session_id) on delete cascade;

comment on column tb_earphone_logs.exam_session_id is
  '이 판정이 속한 응시 시도(세션). 개명 이전 레코드는 NULL — 당시엔 (exam_id, user_id)'
  ' 기준이라 세션에 매핑할 방법이 없다.';

create index idx_tb_earphone_logs_session on tb_earphone_logs (exam_session_id, checked_at desc);

-- ── tb_gaze_calibrations ──
drop index if exists idx_tb_gaze_calibrations_exam_user;

alter table tb_gaze_calibrations
  drop constraint if exists gaze_calibrations_exam_id_fkey,
  drop constraint if exists gaze_calibrations_user_id_fkey,
  drop column if exists exam_id,
  drop column if exists user_id;

alter table tb_gaze_calibrations
  add column exam_session_id integer references tb_exam_session (exam_session_id) on delete cascade;

comment on column tb_gaze_calibrations.exam_session_id is
  '이 캘리브레이션이 속한 응시 시도(세션). 개명 이전 레코드는 NULL — 당시엔'
  ' (exam_id, user_id) 기준이라 세션에 매핑할 방법이 없다.';

create index idx_tb_gaze_calibrations_session on tb_gaze_calibrations (exam_session_id, created_at desc);
