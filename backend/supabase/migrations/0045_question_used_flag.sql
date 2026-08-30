-- =========================================================
-- tb_question.used: 문항 풀 활성화 플래그
-- =========================================================
-- tb_question에 있다고 다 실제 시험에 나가는 게 아니다 — 테스트로 만든 초안,
-- 아직 검수 안 된 문항이 같은 테이블에 섞여 있다. findByPart(세션 시작 시
-- 문항 풀 랜덤 선택)가 이 플래그로 걸러지도록 한다. 기본값은 false로 둬서,
-- 새로 생성되는 문항(AI 문항 생성 파이프라인 포함)은 명시적으로 켜주기
-- 전까진 실제 시험에 노출되지 않는다.

alter table tb_question
  add column used boolean not null default false;

comment on column tb_question.used is '실제 시험 문항 풀에 노출할지 여부 — findByPart는 이 값이 true인 것만 후보로 삼는다';

-- speaking_v0(0044에서 넣은 상황묘사/주제말하기/듣고말하기 확정 6개)만 켠다.
-- 그 외 기존 말하기 문항 15개(테스트/드래프트로 확인됨)와 쓰기 문항 10개
-- (현재 시험 흐름의 SECTION_ORDER에 없어 애초에 안 쓰임)는 기본값 false로 둔다.
update tb_question
set used = true
where content ->> 'imageUrl' in (
  'speaking-v0/situation-description-01.png',
  'speaking-v0/situation-description-02.png',
  'speaking-v0/read-and-explain-01.png',
  'speaking-v0/read-and-explain-02.png'
)
or content ->> 'audioUrl' in (
  'speaking-v0/answer-question-01.wav',
  'speaking-v0/answer-question-02.wav'
);
