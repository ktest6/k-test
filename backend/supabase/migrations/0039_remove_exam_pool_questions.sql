-- =========================================================
-- 회차(Exam) 개념 제거 — 항시 응시 + 문항 풀 랜덤 배정
-- =========================================================
-- "회차 신청 → 정해진 문항 세트로 시험" 모델을 없애고, 언제든 시작 가능한
-- 세션 하나(= 시도 하나) 기준으로 바꾼다. 문항은 더 이상 회차에 배정되지
-- 않고, 세션 시작 시 파트별 풀에서 애플리케이션 계층이 세션 id를 시드로
-- 결정적 랜덤 선택한다(ExamSessionQuestionService 참고) — 그래서 별도
-- 배정 테이블이 필요 없다.
--
-- 본인인증/이어폰/시선 캘리브레이션 판정 로그는 회차+응시자 기준
-- (exam_id, user_id)에서 세션 하나(exam_session_id) 기준으로 되돌린다 —
-- 같은 시험을 여러 번 볼 수 있게 되면서 회차 기준으로는 어느 시도의
-- 기록인지 구분이 안 되기 때문이다(identity_logs는 원래 이 방식이었다가
-- 0016에서 회차 기준으로 바뀌었던 것을 다시 되돌리는 것).

-- ── 회차별 문항 배정 제거 ──
drop table if exists tb_exam_question;

-- ── 회차 신청 제거 ──
drop table if exists tb_exam_application;

-- ── tb_exam_session에서 회차 참조 제거 ──
alter table tb_exam_session
  drop column if exists exam_id;

-- ── 회차 테이블 자체 제거 ──
drop table if exists tb_exam;

-- ── identity_logs: (exam_id, user_id) → exam_session_id ──
drop index if exists idx_identity_logs_exam_user;

alter table identity_logs
  drop constraint if exists identity_logs_exam_id_fkey,
  drop constraint if exists identity_logs_user_id_fkey,
  drop column if exists exam_id,
  drop column if exists user_id;

alter table identity_logs
  add column exam_session_id integer references tb_exam_session (exam_session_id) on delete cascade;

create index idx_identity_logs_session on identity_logs (exam_session_id, created_at desc);

-- ── tb_earphone_logs: (exam_id, user_id) → exam_session_id ──
drop index if exists idx_earphone_logs_exam_user;

alter table tb_earphone_logs
  drop constraint if exists earphone_logs_exam_id_fkey,
  drop constraint if exists earphone_logs_user_id_fkey,
  drop column if exists exam_id,
  drop column if exists user_id;

alter table tb_earphone_logs
  add column exam_session_id integer references tb_exam_session (exam_session_id) on delete cascade;

create index idx_tb_earphone_logs_session on tb_earphone_logs (exam_session_id, checked_at desc);

-- ── tb_gaze_calibrations: (exam_id, user_id) → exam_session_id ──
drop index if exists idx_gaze_calibrations_exam_user;

alter table tb_gaze_calibrations
  drop constraint if exists gaze_calibrations_exam_id_fkey,
  drop constraint if exists gaze_calibrations_user_id_fkey,
  drop column if exists exam_id,
  drop column if exists user_id;

alter table tb_gaze_calibrations
  add column exam_session_id integer references tb_exam_session (exam_session_id) on delete cascade;

create index idx_tb_gaze_calibrations_session on tb_gaze_calibrations (exam_session_id, created_at desc);

comment on column identity_logs.exam_session_id is '이 본인인증이 속한 응시 시도(세션). 같은 시험을 여러 번 볼 수 있어 회차가 아니라 세션 기준.';
comment on column tb_earphone_logs.exam_session_id is '이 판정이 속한 응시 시도(세션).';
comment on column tb_gaze_calibrations.exam_session_id is '이 캘리브레이션이 속한 응시 시도(세션).';
