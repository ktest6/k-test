-- 부정행위 감지(모니터링 이벤트 누적 등)로 인한 실격 상태. BLOCKED(SESSION-10)와
-- 같은 방식으로 추가한다 — 재시작/답안 제출은 막히지만 문항/답안 조회는 계속 가능.
alter type session_status add value 'DISQUALIFIED';
