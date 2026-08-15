/** 듣기/말하기 문항의 3가지 유형. 회차 하나당 유형별로 2문항씩 고정 출제된다. */
export enum QuestionSectionType {
  /** 상황 묘사하기 — 준비 40초 / 응답 60초 */
  SITUATION_DESCRIPTION = 'SITUATION_DESCRIPTION',
  /** 읽고 설명하기 — 준비 70초 / 응답 80초 */
  READ_AND_EXPLAIN = 'READ_AND_EXPLAIN',
  /** 질문에 대답하기(듣고 따라 말하기) — 준비 20초 / 응답 30초 */
  ANSWER_QUESTION = 'ANSWER_QUESTION',
}
