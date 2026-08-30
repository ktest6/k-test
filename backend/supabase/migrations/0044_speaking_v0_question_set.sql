-- =========================================================
-- 말하기(speaking) 고정 문항 세트(speaking_v0) 최초 등록
-- =========================================================
-- 상황묘사(SITUATION_DESCRIPTION) 2개, 주제말하기(READ_AND_EXPLAIN) 2개,
-- 듣고 말하기(ANSWER_QUESTION) 2개, 총 6개. 확정된 이미지/음성은 이미
-- question-assets 버킷의 speaking-v0/ 경로에 업로드되어 있다.
--
-- 지시문 표기 규칙: 문항 작성자가 "A / B" 형태로 준 문장 중 앞부분(A)을
-- content.instruction(문항별 실제 질문)에, 뒷부분(B)을 content.guideTexts에
-- 넣는다(항목마다 다른 값 — 유형 공통 고정문구는 아님).
--
-- checklist_item의 weight는 채점 기준이 아직 확정되지 않아 문항 지시문
-- 구조를 보고 만든 초안이다. 실제 채점 기준을 받으면 새 문항으로 다시
-- 만들지 말고 이 문항들의 체크리스트 행만 교체할 것(tb_question 자체는
-- append-only이지만 체크리스트는 아직 한 번도 채점에 안 쓰인 초안이므로).

with inserted as (
  insert into tb_question (part, content) values
  (
    'SITUATION_DESCRIPTION',
    '{
      "preparationSeconds": 40,
      "responseSeconds": 60,
      "guideTexts": ["사진 속 인물을 보이는대로 말하세요."],
      "instruction": "사진속 인물에 대해 묘사하세요.",
      "imageUrl": "speaking-v0/situation-description-01.png"
    }'::jsonb
  ),
  (
    'SITUATION_DESCRIPTION',
    '{
      "preparationSeconds": 40,
      "responseSeconds": 60,
      "guideTexts": ["무엇이 위험한지->왜 위험한지->어떻게 해야 하는지를 포함하여 말하세요."],
      "instruction": "동료가 위험한 행동을 하고 있습니다. 경고하세요.",
      "imageUrl": "speaking-v0/situation-description-02.png"
    }'::jsonb
  ),
  (
    'READ_AND_EXPLAIN',
    '{
      "preparationSeconds": 70,
      "responseSeconds": 80,
      "guideTexts": ["80초 동안 말할 수 있습니다."],
      "instruction": "다음 표지가 무슨 의미인지 설명하세요.",
      "imageUrl": "speaking-v0/read-and-explain-01.png"
    }'::jsonb
  ),
  (
    'READ_AND_EXPLAIN',
    '{
      "preparationSeconds": 70,
      "responseSeconds": 80,
      "guideTexts": ["80초 동안 말할 수 있습니다."],
      "instruction": "다음 표지가 무슨 의미인지 설명하세요.",
      "imageUrl": "speaking-v0/read-and-explain-02.png"
    }'::jsonb
  ),
  (
    'ANSWER_QUESTION',
    '{
      "preparationSeconds": 20,
      "responseSeconds": 30,
      "guideTexts": ["질문을 잘 듣고 대답하세요.", "30초 동안 답변할 수 있습니다."],
      "audioUrl": "speaking-v0/answer-question-01.wav"
    }'::jsonb
  ),
  (
    'ANSWER_QUESTION',
    '{
      "preparationSeconds": 20,
      "responseSeconds": 30,
      "guideTexts": ["질문을 잘 듣고 대답하세요.", "30초 동안 답변할 수 있습니다."],
      "audioUrl": "speaking-v0/answer-question-02.wav"
    }'::jsonb
  )
  returning question_id, content ->> 'imageUrl' as image_url, content ->> 'audioUrl' as audio_url
)
insert into tb_question_checklist_item (question_id, code, description, weight, display_order)
select question_id, code, description, weight, display_order
from inserted
join (
  values
    ('speaking-v0/situation-description-01.png', 'c1', '인물의 외형(복장/안전장비 등)을 구체적으로 묘사했는가', 1.0, 0),
    ('speaking-v0/situation-description-01.png', 'c2', '인물이 하고 있는 행동을 구체적으로 묘사했는가', 1.5, 1),
    ('speaking-v0/situation-description-01.png', 'c3', '주변 상황/배경(작업 현장 등)을 언급했는가', 1.0, 2),

    ('speaking-v0/situation-description-02.png', 'c1', '무엇이 위험한 행동인지 구체적으로 지적했는가(예: 안전모 미착용)', 1.5, 0),
    ('speaking-v0/situation-description-02.png', 'c2', '왜 위험한지 이유를 설명했는가', 1.0, 1),
    ('speaking-v0/situation-description-02.png', 'c3', '어떻게 해야 하는지 조치를 제안했는가', 1.5, 2),

    ('speaking-v0/read-and-explain-01.png', 'c1', '표지판 문구(근로자 쉼터)의 의미를 정확히 설명했는가', 1.5, 0),
    ('speaking-v0/read-and-explain-01.png', 'c2', '이 장소/표지가 왜 필요한지(휴식의 중요성 등)를 설명했는가', 1.5, 1),
    ('speaking-v0/read-and-explain-01.png', 'c3', '표지판의 목적/기능을 설명했는가', 1.0, 2),

    ('speaking-v0/read-and-explain-02.png', 'c1', '표지판 문구(비상대피로)의 의미를 정확히 설명했는가', 1.5, 0),
    ('speaking-v0/read-and-explain-02.png', 'c2', '화살표가 나타내는 방향(대피 방향)의 의미를 설명했는가', 1.0, 1),
    ('speaking-v0/read-and-explain-02.png', 'c3', '이 표지가 왜 필요한지(비상시 대피 안내)를 설명했는가', 1.5, 2),

    ('speaking-v0/answer-question-01.wav', 'c1', '질문에서 요구한 내용에 맞게 답변했는가', 1.5, 0),
    ('speaking-v0/answer-question-01.wav', 'c2', '질문의 핵심 어휘(지각 관련)를 이해하고 적절히 반응했는가', 1.0, 1),

    ('speaking-v0/answer-question-02.wav', 'c1', '질문에서 요구한 내용에 맞게 답변했는가', 1.5, 0),
    ('speaking-v0/answer-question-02.wav', 'c2', '질문의 핵심 어휘(못 관련)를 이해하고 적절히 반응했는가', 1.0, 1)
) as checklist (asset_path, code, description, weight, display_order)
  on checklist.asset_path = coalesce(inserted.image_url, inserted.audio_url);
