-- =========================================================
-- 관리자 계정을 tb_user에서 tb_admin으로 분리
-- =========================================================
-- 관리자 페이지를 본격적으로 만들면서, tb_user가 응시자 전용 필드
-- (nationality/birth_date/id_type/id_number/약관동의 등)를 관리자
-- 예외 처리(nullable + CHECK)로 억지로 같이 들고 있던 걸 정리한다.
-- 관리자는 신분증 대조 대상이 아니라 first_name/last_name 분리도 필요
-- 없어서 tb_admin은 그냥 name 하나만 둔다.
-- 기존 데이터는 이 변경으로 전부 초기화한다(요청에 따라 보존하지 않음).

truncate table tb_user cascade;

alter table tb_user
  drop constraint chk_user_examinee_fields_required_for_user_role,
  drop column role,
  alter column nationality set not null,
  alter column birth_date set not null,
  alter column id_type set not null,
  alter column id_number set not null,
  alter column terms_agreed_at set not null,
  alter column privacy_agreed_at set not null;

comment on table tb_user is '응시자 계정 — 관리자는 tb_admin에서 별도 관리';

drop type if exists user_role;

create table tb_admin (
  admin_id       serial primary key,
  email          varchar(255) not null unique,
  password       varchar(255) not null,
  name           varchar(100) not null,
  login_attempts integer not null default 0,
  last_login_at  timestamptz,
  created_at     timestamptz not null default now(),
  modified_at    timestamptz not null default now(),
  deleted_at     timestamptz
);

comment on table tb_admin is '관리자 계정 — 응시자(tb_user)와 완전히 분리';
comment on column tb_admin.name is '관리자 이름 (신분증 대조 대상 아님, 성/이름 분리 불필요)';

alter table tb_admin enable row level security;
