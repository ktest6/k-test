-- =========================================================
-- 고정 문항 시드 데이터
-- =========================================================
-- 회차 무관 고정 문항 세트(QUESTION-00). AI가 만들고 검수 확정한
-- writing_v0 세트를 그대로 옮겨왔다. `supabase db reset`(로컬) 시
-- 자동 실행되며, 원격 프로젝트에는 이미 동일한 내용으로 직접
-- INSERT되어 있다(재실행 시 중복 삽입되므로 원격에는 다시 돌리지 말 것).

insert into tb_question (mode, version, part, content, checklist_items) values
(
  'writing',
  'writing_v0',
  'work_log',
  '{
    "item_id": "WRT-001",
    "prompt": "오늘 한 작업을 작업일지에 쓰세요. ① 무슨 작업을 했는지 ② 어떤 문제가 있었는지 ③ 어떻게 해결했는지 쓰세요.",
    "expected_register": "formal",
    "reference_keywords": ["작업", "문제", "처리", "해결"]
  }'::jsonb,
  '[
    {"id": "c1", "description": "무슨 작업을 했는지 기록했는가", "weight": 1.0},
    {"id": "c2", "description": "발생한 문제를 기록했는가", "weight": 1.5},
    {"id": "c3", "description": "문제를 어떻게 처리했는지(결과 포함) 기록했는가", "weight": 1.5}
  ]'::jsonb
),
(
  'writing',
  'writing_v0',
  'messenger_report',
  '{
    "item_id": "WRT-002",
    "prompt": "몸이 아파서 내일 회사에 못 갑니다. 반장님에게 보내는 메시지를 쓰세요. ① 내일 못 가는 것 ② 왜 못 가는지 ③ 언제 다시 나올 수 있는지 쓰세요.",
    "expected_register": "polite",
    "reference_keywords": ["아프", "내일", "출근", "죄송"]
  }'::jsonb,
  '[
    {"id": "c1", "description": "내일 출근하지 못한다는 사실을 알렸는가", "weight": 1.5},
    {"id": "c2", "description": "출근하지 못하는 이유를 말했는가", "weight": 1.0},
    {"id": "c3", "description": "언제 다시 출근할 수 있는지(또는 모르면 알리겠다는 것)를 말했는가", "weight": 1.0},
    {"id": "c4", "description": "반장님에게 맞는 높임 표현을 사용했는가", "weight": 0.5}
  ]'::jsonb
),
(
  'writing',
  'writing_v0',
  'hazard_report',
  '{
    "item_id": "WRT-003",
    "prompt": "창고 선반이 한쪽으로 기울어져 있습니다. 물건이 떨어질 수 있습니다. 안전 관리자에게 알리는 글을 쓰세요. ① 무엇이 위험한지 ② 어디에 있는지 ③ 어떤 조치가 필요한지 쓰세요.",
    "expected_register": "formal",
    "reference_keywords": ["선반", "창고", "기울", "위험", "떨어지"]
  }'::jsonb,
  '[
    {"id": "c1", "description": "무엇이 어떻게 위험한지 구체적으로 알렸는가", "weight": 1.5},
    {"id": "c2", "description": "위험한 곳이 어디인지 위치를 알렸는가", "weight": 1.5},
    {"id": "c3", "description": "필요한 조치를 요청했는가", "weight": 1.0}
  ]'::jsonb
),
(
  'writing',
  'writing_v0',
  'handover_memo',
  '{
    "item_id": "WRT-004",
    "prompt": "오늘 일이 끝났습니다. 다음 근무자에게 메모를 남기세요. ① 끝낸 작업 ② 아직 안 끝난 작업 ③ 조심할 것을 쓰세요.",
    "expected_register": "polite",
    "reference_keywords": ["작업", "끝", "남", "조심", "주의"]
  }'::jsonb,
  '[
    {"id": "c1", "description": "완료한 작업을 알렸는가", "weight": 1.0},
    {"id": "c2", "description": "아직 끝나지 않은 작업(다음 근무자가 해야 할 일)을 알렸는가", "weight": 1.5},
    {"id": "c3", "description": "주의할 점이나 특이사항을 알렸는가", "weight": 1.5}
  ]'::jsonb
),
(
  'writing',
  'writing_v0',
  'supply_request',
  '{
    "item_id": "WRT-005",
    "prompt": "작업용 장갑이 거의 없습니다. 사무실에 요청하는 글을 쓰세요. ① 무엇이 필요한지 ② 몇 개 필요한지 ③ 언제까지 필요한지 쓰세요.",
    "expected_register": "formal",
    "reference_keywords": ["장갑", "필요", "개", "요청"]
  }'::jsonb,
  '[
    {"id": "c1", "description": "무엇이 필요한지 알렸는가", "weight": 1.5},
    {"id": "c2", "description": "필요한 수량을 알렸는가", "weight": 1.0},
    {"id": "c3", "description": "언제까지 필요한지(또는 왜 급한지)를 알렸는가", "weight": 1.0}
  ]'::jsonb
);
