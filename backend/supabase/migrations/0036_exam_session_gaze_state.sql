alter table tb_exam_session add column gaze_state jsonb;
comment on column tb_exam_session.gaze_state is '/monitoring/analyze의 연속 시선 상태(previous_gaze_state round-trip). FastAPI가 이 상태를 메모리에 들고 있지 않아, 백엔드가 세션 단위로 최신 상태를 보관했다가 다음 analyze 요청에 그대로 돌려준다.';
