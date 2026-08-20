alter table tb_proctoring_events
  add column snapshot_path text;
comment on column tb_proctoring_events.snapshot_path is
  'Storage(proctoring-snapshots 버킷) 상 해당 이벤트가 감지된 웹캠 프레임 경로. 위반이 감지된 프레임만 저장한다(NORMAL이면 NULL) — 매 프레임을 다 저장하면 스토리지 비용이 커진다.';
