-- 백엔드는 항상 service_role로만 Supabase에 접속한다(anon/authenticated 키는
-- 코드 어디서도 쓰지 않는다). service_role은 RLS를 무조건 우회하므로 이
-- 정책이 실제 애플리케이션 동작에 영향을 주지는 않는다 — 목적은 "anon/
-- authenticated 키가 실수로 노출되거나 나중에 프론트에서 Supabase에 직접
-- 붙는 코드가 생기더라도 DB가 기본적으로 아무것도 내주지 않는다"는 걸
-- 암묵적 설정이 아니라 명시적인 정책으로 문서화해두는 것이다.

alter table tb_question_checklist_item enable row level security;

do $$
declare
  t text;
begin
  foreach t in array array[
    'identity_logs',
    'tb_admin',
    'tb_answers',
    'tb_document',
    'tb_exam',
    'tb_exam_application',
    'tb_exam_question',
    'tb_exam_results',
    'tb_exam_session',
    'tb_proctoring_events',
    'tb_question',
    'tb_question_checklist_item',
    'tb_score',
    'tb_user'
  ]
  loop
    execute format(
      'create policy deny_anon_authenticated on %I for all to anon, authenticated using (false) with check (false);',
      t
    );
  end loop;
end $$;
