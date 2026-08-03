-- 답안(말하기) 녹음 파일 업로드용 버킷. 채점은 별도 assessment 서비스가
-- audio.url(공개 https URL)을 그대로 내려받아 처리하므로 public으로 둔다
-- (신분증 등 민감정보를 담는 identity-docs와는 성격이 다름).
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'answer-audio',
  'answer-audio',
  true,
  20971520, -- 20MB, assessment 서비스의 업로드 한도와 동일
  array['audio/webm', 'audio/wav', 'audio/x-wav', 'audio/mpeg', 'audio/mp4', 'audio/ogg']
)
on conflict (id) do update set
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;
