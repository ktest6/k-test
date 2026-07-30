-- =========================================================
-- 시험 회차 정원(capacity) 추가
-- =========================================================
-- 상태(SCHEDULED/OPEN/CLOSED)는 컬럼으로 저장하지 않는다 — open_at/close_at과
-- 현재 시각을 비교해 애플리케이션 계층에서 계산한다
-- (src/modules/exam/domain/exam-status.util.ts). 정원 미달/초과로 자동
-- 마감하는 로직은 없음(수동 마감 요구사항 없음, EXAM-03 신청 기능에서 정원
-- 초과 여부만 별도로 체크할 예정).

alter table tb_exam
  add column capacity integer not null default 0;

comment on column tb_exam.capacity is '정원';
