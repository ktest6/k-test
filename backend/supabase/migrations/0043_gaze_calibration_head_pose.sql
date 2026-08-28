-- =========================================================
-- tb_gaze_calibrations: head_yaw_center/head_pitch_center 추가
-- =========================================================
-- anti-cheat 쪽 시선 캘리브레이션·모니터링 정책이 Eye Direction만이 아니라
-- Head Pose(고개 방향)까지 함께 보정하도록 바뀌었다. POST /monitoring/analyze가
-- 이제 eye_yaw_center/eye_pitch_center/head_yaw_center/head_pitch_center
-- 네 값을 전부 필수로 요구해서(하나라도 없으면 422), 캘리브레이션 결과에
-- head 기준값도 같이 저장해야 한다.
--
-- 이 컬럼 도입 이전 캘리브레이션 기록은 head pose 개념 자체가 없던 시절이라
-- 값을 알 수 없다 — 0으로 채워 넣는다(이미 끝난 세션들의 과거 기록이라 실질적
-- 영향 없음).

alter table tb_gaze_calibrations
  add column head_yaw_center numeric(8, 4) not null default 0,
  add column head_pitch_center numeric(8, 4) not null default 0;

alter table tb_gaze_calibrations
  alter column head_yaw_center drop default,
  alter column head_pitch_center drop default;

comment on column tb_gaze_calibrations.head_yaw_center is '화면 중앙 응시 시 Head Yaw 기준값 — 이후 모니터링(ANALYZE)에서 고개 이탈 판정에 재사용';
comment on column tb_gaze_calibrations.head_pitch_center is '화면 중앙 응시 시 Head Pitch 기준값';
