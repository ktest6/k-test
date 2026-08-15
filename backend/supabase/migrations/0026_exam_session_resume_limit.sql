-- =========================================================
-- 시험 세션 재개(재시작) 남용 방지
-- =========================================================
-- 진행중인 세션이 있는데도 "시험 시작" API를 반복 호출하면(=재개 시도)
-- 계속 재진입할 수 있었다. 재개 시도가 3번째가 되면 더 이상 진행하지
-- 못하도록 세션을 BLOCKED 상태로 전환한다 — 문항/답안 조회는 계속
-- 가능하고(EXPIRED/SUBMITTED와 동일 정책), 재시작과 답안 제출만 막힌다.

alter type session_status add value 'BLOCKED';

alter table tb_exam_session
  add column resume_count int not null default 0;

comment on column tb_exam_session.resume_count is '재개(재시작) 시도 횟수. 3에 도달하면 status가 BLOCKED로 전환된다.';
