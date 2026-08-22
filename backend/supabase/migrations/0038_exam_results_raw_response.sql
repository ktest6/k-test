-- tb_score(answer_id, raw_response)와 같은 철학 — /finalize 응답을 억지로 컬럼별로
-- 분해해서 담다가 필드를 누락시키기보다(item_coverage, mode_results, warnings,
-- meta.safe_to_show_candidate 등은 애초에 컬럼이 없었다), 원본 응답 전체를
-- raw_response에 그대로 저장한다. final_grade/percentile/domain_scores/
-- cross_validation_signals는 빠른 조회·필터링용으로 계속 채워 넣는다(중복이지만
-- 조회 편의를 위해 유지).
alter table tb_exam_results
  add column raw_response jsonb;

comment on column tb_exam_results.raw_response is '/finalize 응답 원본 전체(가공 없음) — 문항별 상세는 tb_score에서 조립.';

-- percentile은 assessment가 소수점(예: 50.7)으로 내려주는데 컬럼이 INT라 반올림
-- 손실이 생긴다. NUMERIC으로 넓혀서 원본 값을 그대로 저장할 수 있게 한다.
alter table tb_exam_results
  alter column percentile type numeric using percentile::numeric;

-- 세션 하나당 최종 결과는 하나(재요청 시 덮어쓰기 upsert).
alter table tb_exam_results
  add constraint uq_exam_results_session unique (exam_session_id);
