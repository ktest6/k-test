-- =========================================================
-- K-TEST ERD (PostgreSQL / Supabase 호환)
-- =========================================================

-- ENUM 타입 먼저 정의 (Postgres는 CREATE TYPE으로 선언 후 컬럼에서 참조)
CREATE TYPE user_role AS ENUM ('USER', 'ADMIN');
CREATE TYPE session_status AS ENUM ('INPROGRESS', 'SUBMITTED', 'EXPIRED');
CREATE TYPE answer_type AS ENUM ('TEXT', 'AUDIO');
CREATE TYPE answer_status AS ENUM ('DRAFT', 'FINAL');
CREATE TYPE proctoring_event_type AS ENUM ('TAB_SWITCH', 'PASTE', 'DUAL_MONITOR', 'FACE_MISMATCH', 'OBJECT_DETECTED', 'DISCONNECT');
CREATE TYPE proctoring_severity AS ENUM ('LOW', 'MEDIUM', 'HIGH');

-- =========================================================
-- Tables
-- =========================================================

CREATE TABLE tb_exam (
	exam_id       SERIAL PRIMARY KEY,
	round_name    VARCHAR(20) NOT NULL,
	open_at       TIMESTAMP NOT NULL,
	close_at      TIMESTAMP NOT NULL,
	created_at    TIMESTAMP NOT NULL DEFAULT now(),
	modified_at   TIMESTAMP NOT NULL DEFAULT now(),
	deleted_at    TIMESTAMP
);
COMMENT ON TABLE tb_exam IS '시험 회차';
COMMENT ON COLUMN tb_exam.round_name IS '시험 회차명';
COMMENT ON COLUMN tb_exam.open_at IS '시험 시작 일자';
COMMENT ON COLUMN tb_exam.close_at IS '시험 종료 일자';

CREATE TABLE tb_user (
	user_id         SERIAL PRIMARY KEY,
	email           VARCHAR(100) NOT NULL UNIQUE,
	password        VARCHAR(255) NOT NULL,
	name            VARCHAR(50) NOT NULL,
	role            user_role NOT NULL DEFAULT 'USER',
	login_attempts  INT NOT NULL DEFAULT 0,
	last_login_at   TIMESTAMP,
	created_at      TIMESTAMP NOT NULL DEFAULT now(),
	modified_at     TIMESTAMP NOT NULL DEFAULT now(),
	deleted_at      TIMESTAMP
);
COMMENT ON TABLE tb_user IS '사용자';
COMMENT ON COLUMN tb_user.login_attempts IS '로그인 실패 횟수';
COMMENT ON COLUMN tb_user.last_login_at IS '마지막 로그인 시간';

CREATE TABLE tb_question (
	question_id      SERIAL PRIMARY KEY,
	exam_id          INT NOT NULL REFERENCES tb_exam(exam_id),
	question_no      INT NOT NULL,
	part             VARCHAR(50) NOT NULL,
	content          JSONB,
	checklist_items  JSONB,
	created_at       TIMESTAMP NOT NULL DEFAULT now(),
	modified_at      TIMESTAMP NOT NULL DEFAULT now(),
	deleted_at       TIMESTAMP
);
COMMENT ON TABLE tb_question IS '문항';
COMMENT ON COLUMN tb_question.part IS '문항 파트 (상황묘사, 메신저 대화)';
COMMENT ON COLUMN tb_question.content IS '지문/이미지/스크립트 등';
COMMENT ON COLUMN tb_question.checklist_items IS '문항별 체크리스트 항목';

CREATE TABLE tb_exam_session (
	exam_session_id       SERIAL PRIMARY KEY,
	user_id               INT NOT NULL REFERENCES tb_user(user_id),
	exam_id               INT NOT NULL REFERENCES tb_exam(exam_id),
	started_at            TIMESTAMP NOT NULL DEFAULT now(),
	status                session_status NOT NULL DEFAULT 'INPROGRESS',
	current_question_id   INT REFERENCES tb_question(question_id),
	last_saved_at         TIMESTAMP,
	submitted_at          TIMESTAMP,
	created_at            TIMESTAMP NOT NULL DEFAULT now(),
	modified_at           TIMESTAMP NOT NULL DEFAULT now(),
	deleted_at            TIMESTAMP
);
COMMENT ON TABLE tb_exam_session IS '응시 세션';
COMMENT ON COLUMN tb_exam_session.started_at IS '서버 기준 시작 시각';
COMMENT ON COLUMN tb_exam_session.current_question_id IS '마지막 진입 문항 ID';
COMMENT ON COLUMN tb_exam_session.last_saved_at IS '마지막 저장 시각';
COMMENT ON COLUMN tb_exam_session.submitted_at IS '제출 완료 시각';

CREATE TABLE tb_answers (
	answer_id         SERIAL PRIMARY KEY,
	exam_session_id   INT NOT NULL REFERENCES tb_exam_session(exam_session_id),
	question_id       INT NOT NULL REFERENCES tb_question(question_id),
	type              answer_type NOT NULL,
	content_text      VARCHAR(1000),
	audio_file_url    VARCHAR(255),
	status            answer_status NOT NULL DEFAULT 'DRAFT',
	created_at        TIMESTAMP NOT NULL DEFAULT now(),
	modified_at       TIMESTAMP NOT NULL DEFAULT now(),
	deleted_at        TIMESTAMP
);
COMMENT ON TABLE tb_answers IS '답안';
COMMENT ON COLUMN tb_answers.content_text IS '쓰기 답안';
COMMENT ON COLUMN tb_answers.audio_file_url IS '음성 답안 (Supabase Storage 경로)';

CREATE TABLE tb_score (
	score_id       SERIAL PRIMARY KEY,
	answer_id      INT NOT NULL REFERENCES tb_answers(answer_id),
	raw_response   JSONB NOT NULL,
	created_at     TIMESTAMP NOT NULL DEFAULT now(),
	modified_at    TIMESTAMP NOT NULL DEFAULT now(),
	deleted_at     TIMESTAMP
);
COMMENT ON TABLE tb_score IS '문항별 채점 결과';
COMMENT ON COLUMN tb_score.raw_response IS '채점 응답 (/score 응답 원본)';

CREATE TABLE tb_exam_results (
	exam_results_id            SERIAL PRIMARY KEY,
	exam_session_id            INT NOT NULL REFERENCES tb_exam_session(exam_session_id),
	final_grade                VARCHAR(20) NOT NULL,
	percentile                 INT,
	domain_scores               JSONB,
	item_contributions          JSONB,
	cross_validation_signals    JSONB,
	created_at                 TIMESTAMP NOT NULL DEFAULT now(),
	modified_at                TIMESTAMP NOT NULL DEFAULT now(),
	deleted_at                 TIMESTAMP
);
COMMENT ON TABLE tb_exam_results IS '최종 시험 결과 (점수 결합 모델 응답)';
COMMENT ON COLUMN tb_exam_results.domain_scores IS '영역별 점수';
COMMENT ON COLUMN tb_exam_results.item_contributions IS '문항별 기여 내역';
COMMENT ON COLUMN tb_exam_results.cross_validation_signals IS '말하기/쓰기 교차검증 신호';

CREATE TABLE tb_proctoring_events (
	proctoring_events_id   SERIAL PRIMARY KEY,
	exam_session_id        INT NOT NULL REFERENCES tb_exam_session(exam_session_id),
	event_type             proctoring_event_type NOT NULL,
	severity               proctoring_severity NOT NULL,
	meta                   JSONB,
	created_at             TIMESTAMP NOT NULL DEFAULT now(),
	modified_at            TIMESTAMP NOT NULL DEFAULT now(),
	deleted_at             TIMESTAMP
);
COMMENT ON TABLE tb_proctoring_events IS '부정행위 감독 이벤트';
COMMENT ON COLUMN tb_proctoring_events.meta IS '근거 이벤트, 신뢰도 등';

-- =========================================================
-- Unique Constraints (선택 — 비즈니스 룰 확정되면 적용)
-- =========================================================

-- 한 유저는 한 회차에 세션 1개만 (재응시 정책 확정 후 적용)
-- ALTER TABLE tb_exam_session ADD CONSTRAINT uq_session_user_exam UNIQUE (user_id, exam_id);

-- 답안 1개당 채점 결과 1개 (재채점 미허용 시 적용)
-- ALTER TABLE tb_score ADD CONSTRAINT uq_score_answer UNIQUE (answer_id);


-- =========================================================
-- Row Level Security
-- =========================================================
-- 인가(authorization)는 애플리케이션 계층(NestJS Guard)에서 처리하므로
-- 여기서는 정책(policy)을 만들지 않고 RLS만 활성화한다.
-- RLS가 켜져 있으면 anon/authenticated 키로는 기본적으로 모든 접근이 차단되고,
-- 백엔드가 사용하는 service_role key만 RLS를 우회해 접근 가능하다.

ALTER TABLE tb_exam ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_user ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_question ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_exam_session ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_score ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_exam_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE tb_proctoring_events ENABLE ROW LEVEL SECURITY;

