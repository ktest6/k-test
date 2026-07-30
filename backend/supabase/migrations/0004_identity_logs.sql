-- =========================================================
-- 시험 시작 전 본인인증 (신분증-얼굴 대조) 로그 + Storage 버킷
-- =========================================================
-- 흐름: 프론트가 신분증/수험표 이미지와 웹캠 캡처 이미지를 Supabase Storage에
-- 올린 뒤, 그 경로(id_card_path/face_path)만 백엔드 POST /identity/verify로
-- 전달한다. 백엔드는 경로 소유권 + 세션 소유권을 확인하고, 얼굴 대조를 맡을
-- FastAPI 서비스가 아직 연동되지 않아 matched/confidence는 당분간 NULL로
-- 기록된다 (src/modules/identity-verification/application/services/
-- identity-image-verification.service.ts 참고).

-- 업로드 경로는 백엔드가 signed upload URL 발급 시점에 직접 정하므로
-- (POST /identity/upload-url), 여기서는 형식/용량만 버킷 레벨에서 한 번 더
-- 강제한다 — 프론트 검증을 우회해도 서버가 막는다.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'identity-docs',
  'identity-docs',
  false,
  5242880, -- 5MB
  array['image/jpeg', 'image/png', 'application/pdf']
)
on conflict (id) do update set
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

create table identity_logs (
  id uuid primary key default gen_random_uuid(),
  exam_session_id integer not null references tb_exam_session (exam_session_id) on delete cascade,
  id_card_path text not null,
  face_path text not null,
  matched boolean,
  confidence numeric(5, 4),
  verified_at timestamptz,
  created_at timestamptz not null default now()
);
comment on table identity_logs is '시험 시작 전 본인인증(신분증-얼굴 대조) 결과 로그';
comment on column identity_logs.id_card_path is 'Storage 상 신분증/수험표 이미지 경로 (대조 완료 후 삭제 예정 — 감사 목적으로 경로만 보존)';
comment on column identity_logs.face_path is 'Storage 상 웹캠 캡처 이미지 경로 (대조 완료 후 삭제 예정)';
comment on column identity_logs.matched is '대조 결과. FastAPI 연동 전까지는 NULL(미검증)';
comment on column identity_logs.confidence is '대조 신뢰도 (0~1)';
comment on column identity_logs.verified_at is '실제 대조가 수행된 시각 (NULL이면 아직 대조되지 않음)';

create index idx_identity_logs_session on identity_logs (exam_session_id, created_at desc);

alter table identity_logs enable row level security;
