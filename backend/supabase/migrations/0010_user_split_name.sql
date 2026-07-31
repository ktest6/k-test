-- =========================================================
-- tb_user.name을 first_name/last_name으로 분리
-- =========================================================
-- FastAPI 얼굴 대조 서비스가 성(last_name)/이름(first_name)을 각각 요구해서
-- 하나의 영문성명(name) 컬럼을 둘로 나눈다. 기존 데이터는 개발 단계
-- 테스트 데이터뿐이라 보존하지 않고 컬럼을 통째로 교체한다.

alter table tb_user
  drop column name;

alter table tb_user
  add column first_name varchar(100) not null default '',
  add column last_name varchar(100) not null default '';

alter table tb_user
  alter column first_name drop default,
  alter column last_name drop default;

comment on column tb_user.first_name is '이름 (여권 표기 기준) — 응시 당일 신분증 대조용';
comment on column tb_user.last_name is '성 (여권 표기 기준) — 응시 당일 신분증 대조용';
