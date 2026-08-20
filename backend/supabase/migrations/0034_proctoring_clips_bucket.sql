-- 부정행위(모니터링) 위반 전후 구간을 담은 웹캠 영상 클립 보관용 버킷.
-- 감독관 검토용 증거 자료라 proctoring-snapshots와 같이 비공개로 둔다.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'proctoring-clips',
  'proctoring-clips',
  false,
  52428800, -- 50MB, 스냅샷 이미지 대비 훨씬 큰 짧은 영상 클립 기준
  array['video/webm', 'video/mp4', 'video/quicktime']
)
on conflict (id) do update set
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;
