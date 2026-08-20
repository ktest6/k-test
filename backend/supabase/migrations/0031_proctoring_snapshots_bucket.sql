-- 부정행위(모니터링) 위반이 감지된 프레임의 웹캠 스냅샷 보관용 버킷.
-- 감독관 검토용 증거 자료라 identity-docs와 같이 비공개로 둔다.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'proctoring-snapshots',
  'proctoring-snapshots',
  false,
  5242880, -- 5MB
  array['image/jpeg', 'image/png']
)
on conflict (id) do update set
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;
