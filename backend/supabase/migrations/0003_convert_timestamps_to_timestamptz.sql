-- =========================================================
-- TIMESTAMP → TIMESTAMPTZ 전환
-- =========================================================
-- 원인: 0001/0002에서 만든 모든 시간 컬럼이 TIMESTAMP(WITHOUT TIME ZONE)라
-- 타임존 정보 없이 "그 순간의 UTC 벽시계 값"이 그대로 저장된다.
-- now()나 백엔드의 new Date().toISOString()은 항상 UTC 기준이라, KST(UTC+9)로
-- 읽으면 실제 시각보다 정확히 9시간 이전으로 보인다 — Supabase 프로젝트 리전
-- 설정과는 무관한 문제다 (리전은 서버 위치일 뿐, 타임스탬프 표시와는 별개).
--
-- 해결: TIMESTAMPTZ는 절대 시각(instant)을 저장하고 조회하는 세션/클라이언트의
-- 타임존에 맞춰 자동 변환해서 보여준다. 기존에 저장된 값은 "UTC 벽시계 값"이
-- 맞으므로 `AT TIME ZONE 'UTC'`로 재해석해 그대로 변환한다(데이터 자체는 바뀌지
-- 않고 타입만 timezone-aware가 됨). 백엔드 코드는 원래 UTC 기준 값을 넣고
-- 있었으므로 애플리케이션 쪽 수정은 필요 없다.

ALTER TABLE tb_exam
  ALTER COLUMN open_at     TYPE TIMESTAMPTZ USING open_at     AT TIME ZONE 'UTC',
  ALTER COLUMN close_at    TYPE TIMESTAMPTZ USING close_at    AT TIME ZONE 'UTC',
  ALTER COLUMN created_at  TYPE TIMESTAMPTZ USING created_at  AT TIME ZONE 'UTC',
  ALTER COLUMN modified_at TYPE TIMESTAMPTZ USING modified_at AT TIME ZONE 'UTC',
  ALTER COLUMN deleted_at  TYPE TIMESTAMPTZ USING deleted_at  AT TIME ZONE 'UTC';

ALTER TABLE tb_user
  ALTER COLUMN last_login_at     TYPE TIMESTAMPTZ USING last_login_at     AT TIME ZONE 'UTC',
  ALTER COLUMN created_at        TYPE TIMESTAMPTZ USING created_at        AT TIME ZONE 'UTC',
  ALTER COLUMN modified_at       TYPE TIMESTAMPTZ USING modified_at       AT TIME ZONE 'UTC',
  ALTER COLUMN deleted_at        TYPE TIMESTAMPTZ USING deleted_at        AT TIME ZONE 'UTC',
  ALTER COLUMN terms_agreed_at   TYPE TIMESTAMPTZ USING terms_agreed_at   AT TIME ZONE 'UTC',
  ALTER COLUMN privacy_agreed_at TYPE TIMESTAMPTZ USING privacy_agreed_at AT TIME ZONE 'UTC';

ALTER TABLE tb_question
  ALTER COLUMN created_at  TYPE TIMESTAMPTZ USING created_at  AT TIME ZONE 'UTC',
  ALTER COLUMN modified_at TYPE TIMESTAMPTZ USING modified_at AT TIME ZONE 'UTC',
  ALTER COLUMN deleted_at  TYPE TIMESTAMPTZ USING deleted_at  AT TIME ZONE 'UTC';

ALTER TABLE tb_exam_session
  ALTER COLUMN started_at    TYPE TIMESTAMPTZ USING started_at    AT TIME ZONE 'UTC',
  ALTER COLUMN last_saved_at TYPE TIMESTAMPTZ USING last_saved_at AT TIME ZONE 'UTC',
  ALTER COLUMN submitted_at  TYPE TIMESTAMPTZ USING submitted_at  AT TIME ZONE 'UTC',
  ALTER COLUMN created_at    TYPE TIMESTAMPTZ USING created_at    AT TIME ZONE 'UTC',
  ALTER COLUMN modified_at   TYPE TIMESTAMPTZ USING modified_at   AT TIME ZONE 'UTC',
  ALTER COLUMN deleted_at    TYPE TIMESTAMPTZ USING deleted_at    AT TIME ZONE 'UTC';

ALTER TABLE tb_answers
  ALTER COLUMN created_at  TYPE TIMESTAMPTZ USING created_at  AT TIME ZONE 'UTC',
  ALTER COLUMN modified_at TYPE TIMESTAMPTZ USING modified_at AT TIME ZONE 'UTC',
  ALTER COLUMN deleted_at  TYPE TIMESTAMPTZ USING deleted_at  AT TIME ZONE 'UTC';

ALTER TABLE tb_score
  ALTER COLUMN created_at  TYPE TIMESTAMPTZ USING created_at  AT TIME ZONE 'UTC',
  ALTER COLUMN modified_at TYPE TIMESTAMPTZ USING modified_at AT TIME ZONE 'UTC',
  ALTER COLUMN deleted_at  TYPE TIMESTAMPTZ USING deleted_at  AT TIME ZONE 'UTC';

ALTER TABLE tb_exam_results
  ALTER COLUMN created_at  TYPE TIMESTAMPTZ USING created_at  AT TIME ZONE 'UTC',
  ALTER COLUMN modified_at TYPE TIMESTAMPTZ USING modified_at AT TIME ZONE 'UTC',
  ALTER COLUMN deleted_at  TYPE TIMESTAMPTZ USING deleted_at  AT TIME ZONE 'UTC';

ALTER TABLE tb_proctoring_events
  ALTER COLUMN created_at  TYPE TIMESTAMPTZ USING created_at  AT TIME ZONE 'UTC',
  ALTER COLUMN modified_at TYPE TIMESTAMPTZ USING modified_at AT TIME ZONE 'UTC',
  ALTER COLUMN deleted_at  TYPE TIMESTAMPTZ USING deleted_at  AT TIME ZONE 'UTC';

-- 선택 사항: Supabase Studio(Table Editor)나 SQL Editor에서 now() 결과 등을
-- 볼 때 KST로 바로 표시되길 원하면 DB 기본 세션 타임존도 바꿀 수 있다.
-- (TIMESTAMPTZ는 내부적으로 항상 UTC 절대시각으로 저장되므로 이 설정은
-- "표시"에만 영향을 주고 데이터 정확성과는 무관하다.)
-- ALTER DATABASE postgres SET timezone TO 'Asia/Seoul';
