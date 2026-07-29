-- =========================================================
-- 응시자 회원가입: tb_user 신원/동의 항목 추가
-- =========================================================
-- 항목 최소화 원칙: 계정(이메일/비밀번호) + 특정 가능한 최소 신원 정보만 수집.
-- (id_type, id_number) 조합에 유니크 제약을 걸어 동일인이 여러 계정을
-- 만드는 것을 막는다 (여권/외국인등록증 기준).

CREATE TYPE identity_document_type AS ENUM ('PASSPORT', 'ARC');

ALTER TABLE tb_user
  ALTER COLUMN name TYPE VARCHAR(100),
  ADD COLUMN nationality      VARCHAR(100) NOT NULL,
  ADD COLUMN birth_date       DATE NOT NULL,
  ADD COLUMN id_type          identity_document_type NOT NULL,
  ADD COLUMN id_number        VARCHAR(50) NOT NULL,
  ADD COLUMN company_code     VARCHAR(50),
  ADD COLUMN terms_agreed_at  TIMESTAMP NOT NULL,
  ADD COLUMN privacy_agreed_at TIMESTAMP NOT NULL;

ALTER TABLE tb_user
  ADD CONSTRAINT uq_user_identity_document UNIQUE (id_type, id_number);

COMMENT ON COLUMN tb_user.password IS '비밀번호 (bcrypt 해시)';
COMMENT ON COLUMN tb_user.name IS '영문성명 (여권 표기 기준) — 응시 당일 신분증 대조용';
COMMENT ON COLUMN tb_user.nationality IS '국적';
COMMENT ON COLUMN tb_user.birth_date IS '생년월일';
COMMENT ON COLUMN tb_user.id_type IS '신분증 종류 (여권/외국인등록증)';
COMMENT ON COLUMN tb_user.id_number IS '신분증 번호';
COMMENT ON COLUMN tb_user.company_code IS '소속 기업 코드 (B2B, 선택) — 추후 관리자 매칭용';
COMMENT ON COLUMN tb_user.terms_agreed_at IS '이용약관 동의 시각';
COMMENT ON COLUMN tb_user.privacy_agreed_at IS '개인정보처리방침 동의 시각';
