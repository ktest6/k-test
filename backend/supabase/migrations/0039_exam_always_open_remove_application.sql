-- =========================================================
-- 항시 응시 체제로 전환 — 신청/기간/정원 제거
-- =========================================================
-- "회차 신청" 개념을 없애고 언제든 응시 가능하도록 바꾼다. 유일한 시작
-- 제약은 애플리케이션 계층에서 건다 — 한 사용자는 한 번에 하나의 시험만
-- 진행(INPROGRESS)할 수 있다(ExamSessionService.start 참고).

drop table if exists tb_exam_application;

alter table tb_exam
  drop column if exists application_open_at,
  drop column if exists application_close_at,
  drop column if exists open_at,
  drop column if exists close_at,
  drop column if exists capacity;

comment on table tb_exam is '시험 회차 — 항시 응시 체제. 신청/응시 기간·정원 없음, roundName만 식별용으로 남는다.';
