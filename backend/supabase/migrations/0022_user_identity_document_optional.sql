-- =========================================================
-- 회원가입 시 신분증 종류/번호를 선택 입력으로 변경
-- =========================================================
-- 가입 단계에서 신분증 정보를 필수로 받지 않기로 결정(AUTH-02).
-- id_type/id_number는 여전히 함께 채워지거나 함께 비어 있어야 한다는
-- 불변식을 애플리케이션(SignUpDto)에서 강제하므로, DB에는 NOT NULL만
-- 풀고 별도 CHECK 제약은 추가하지 않는다.

alter table tb_user
  alter column id_type drop not null,
  alter column id_number drop not null;
