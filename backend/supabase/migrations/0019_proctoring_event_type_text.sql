-- 최초 설계 당시의 event_type enum(TAB_SWITCH/PASTE/DUAL_MONITOR/FACE_MISMATCH/
-- OBJECT_DETECTED/DISCONNECT)이 실제 모니터링 서비스(부정행위 탐지 AI)가 주는
-- 세분화된 이벤트 타입(FACE_OUT_OF_FRAME, EYE_GAZE_AWAY, HEAD_POSE_AWAY,
-- PHONE_DETECTED 등)과 맞지 않는다. 이 taxonomy는 외부 AI 서비스가 계속
-- 넓혀갈 값이라 우리 스키마에 enum으로 고정하지 않고 자유 텍스트로 둔다.
alter table tb_proctoring_events
  alter column event_type type text using event_type::text;

drop type if exists proctoring_event_type;
