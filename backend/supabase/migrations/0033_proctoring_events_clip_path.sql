alter table tb_proctoring_events
  add column clip_path text;
comment on column tb_proctoring_events.clip_path is
  'Storage(proctoring-clips 버킷) 상 이 이벤트 전후 구간을 담은 웹캠 영상 클립 경로. AI가 createClip:true로 판단한 이벤트에 한해 프런트가 나중에 업로드하므로, 이벤트 생성 시점에는 비어 있다가 사후에 채워질 수 있다.';
