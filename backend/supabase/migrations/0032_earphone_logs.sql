-- 본인인증(identity_logs)과 같은 패턴 — 이어폰 탐지도 시험 시작 전 게이트로
-- 쓰려면(REQUIRE_EARPHONE_CHECK) 나중에(세션 시작 시점에) "통과했는가"를
-- 조회할 수 있어야 하므로 판정 결과를 남긴다. 이미지 자체는 여전히 저장하지
-- 않는다(earphone-detection.service.ts 기존 정책 유지) — 판정 결과만 로그.
create table earphone_logs (
  id uuid primary key default gen_random_uuid(),
  exam_id integer not null references tb_exam (exam_id) on delete cascade,
  user_id integer not null references tb_user (user_id) on delete cascade,
  earphone_detected boolean not null,
  checked_at timestamptz not null default now()
);
comment on table earphone_logs is '시험 시작 전 이어폰 착용 여부 감지 결과 로그(판정 결과만 — 이미지는 저장하지 않음)';
comment on column earphone_logs.earphone_detected is 'true면 이어폰이 탐지됨(통과 아님), false면 미탐지(통과)';

create index idx_earphone_logs_exam_user on earphone_logs (exam_id, user_id, checked_at desc);

alter table earphone_logs enable row level security;
