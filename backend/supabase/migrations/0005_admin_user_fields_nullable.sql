-- =========================================================
-- 관리자 계정 지원: 응시자 전용 필드를 관리자에게는 선택 항목으로 완화
-- =========================================================
-- tb_user는 응시자와 관리자가 같은 테이블을 쓴다. nationality/birth_date/
-- id_type/id_number/terms_agreed_at/privacy_agreed_at는 "응시 당일 신분증
-- 대조"를 위한 응시자 전용 정보라 관리자 계정에는 의미가 없다 — NOT NULL을
-- 풀고, 대신 "USER 역할이면 반드시 채워야 한다"는 불변식을 CHECK 제약으로
-- 옮긴다 (컬럼 자체를 관리자용 별도 테이블로 분리하는 것보다 간단하고,
-- 응시자 쪽 보장은 그대로 유지됨).

alter table tb_user
  alter column nationality drop not null,
  alter column birth_date drop not null,
  alter column id_type drop not null,
  alter column id_number drop not null,
  alter column terms_agreed_at drop not null,
  alter column privacy_agreed_at drop not null;

alter table tb_user
  add constraint chk_user_examinee_fields_required_for_user_role
  check (
    role = 'ADMIN'
    or (
      nationality is not null
      and birth_date is not null
      and id_type is not null
      and id_number is not null
      and terms_agreed_at is not null
      and privacy_agreed_at is not null
    )
  );

comment on constraint chk_user_examinee_fields_required_for_user_role on tb_user is
  '일반 응시자(USER)는 신원/약관동의 정보가 필수이지만, 관리자(ADMIN)는 해당 없음';
