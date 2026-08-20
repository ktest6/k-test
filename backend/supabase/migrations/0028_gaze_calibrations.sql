create table gaze_calibrations (
  id uuid primary key default gen_random_uuid(),
  exam_id integer not null references tb_exam (exam_id) on delete cascade,
  user_id integer not null references tb_user (user_id) on delete cascade,
  eye_yaw_center numeric(8, 4) not null,
  eye_pitch_center numeric(8, 4) not null,
  sample_count integer not null,
  calibrated_at timestamptz not null,
  created_at timestamptz not null default now()
);
comment on table gaze_calibrations is '시험 시작 전 시선 캘리브레이션(개인별 정면 응시 기준값) 결과. 원본 이미지는 저장하지 않고 결과값만 남긴다.';
comment on column gaze_calibrations.eye_yaw_center is '화면 중앙 응시 시 Eye Yaw 기준값 — 이후 모니터링(ANALYZE)에서 시선 이탈 판정에 재사용';
comment on column gaze_calibrations.eye_pitch_center is '화면 중앙 응시 시 Eye Pitch 기준값';
comment on column gaze_calibrations.sample_count is 'Calibration에 실제로 쓰인 유효 이미지 수';

create index idx_gaze_calibrations_exam_user on gaze_calibrations (exam_id, user_id, created_at desc);

alter table gaze_calibrations enable row level security;
