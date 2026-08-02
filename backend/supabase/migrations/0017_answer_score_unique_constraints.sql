-- 세션 하나에서 문항 하나당 답안은 하나(재저장 시 덮어쓰기 upsert)이므로
-- 유니크 제약을 걸어 (exam_session_id, question_id) 조합으로 upsert할 수 있게 한다.
alter table tb_answers
  add constraint uq_answers_session_question unique (exam_session_id, question_id);

-- 답안 하나당 채점 결과도 하나(재채점 시 덮어쓰기 upsert).
alter table tb_score
  add constraint uq_score_answer unique (answer_id);
