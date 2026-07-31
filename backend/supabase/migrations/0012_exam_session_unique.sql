-- =========================================================
-- 응시자당 회차 하나에 활성 세션 하나만 (SESSION-01/02)
-- =========================================================
-- 같은 사용자가 같은 회차에 동시에 "시험 시작"을 두 번 눌러도 세션이
-- 중복 생성되지 않도록 부분 유니크 인덱스로 막는다. soft delete된
-- 세션은 재사용 가능해야 하므로(추후 필요 시) deleted_at is null 조건을
-- 건다.

create unique index uq_exam_session_active_user_exam
  on tb_exam_session (exam_id, user_id)
  where deleted_at is null;
