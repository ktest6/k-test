-- =========================================================
-- 말하기(speaking) 문항 세트를 speaking_v1로 교체
-- =========================================================
-- assessment 팀이 정식으로 만든 체크리스트(문항당 9~10개, description_en·requires
-- 포함)로 speaking_v0(0044)를 대체한다. 이미지/음성 실물은 동일해서(비상대피로·
-- 근로자쉼터·망치질·사다리 사진, 지각·못 음성) question-assets/speaking-v0/ 경로를
-- 그대로 재사용하고 새로 업로드하지 않는다.
--
-- assessment/items/speaking_v1.json 은 이 마이그레이션 시점 기준 status: draft
-- (가중치·requires 조건 모두 "회의 후 확정" 명시)다. 검수 확정 전에 반영을
-- 요청받아 그대로 진행한다 — 나중에 내용이 바뀌면 tb_question은 append-only이니
-- 새 문항으로 다시 넣고 이번에 넣은 행은 used=false로 내린다(체크리스트 자체는
-- 아직 한 번도 채점에 안 쓰인 초안이라 행을 새로 만들지 않고 체크리스트만 교체해도
-- 무방하다 — 0044 때와 같은 예외).
--
-- tb_question_checklist_item에 description_en(리포트 표시용, 채점에 안 쓰임)과
-- requires(보너스 항목을 LLM 대신 코드로 계산하는 AND-of-OR 조건, 예:
-- [["c4"],["c3"],["c5","c6"]]) 컬럼을 추가한다 — assessment의 /score ItemInfo/
-- ChecklistItem 스키마와 대응.

alter table tb_question_checklist_item
  add column description_en varchar(500) not null default '',
  add column requires jsonb not null default '[]'::jsonb;

comment on column tb_question_checklist_item.description_en is '리포트 화면 표시용 영어 문장 — 채점에는 안 쓰인다';
comment on column tb_question_checklist_item.requires is '이 항목을 LLM 대신 앞 항목들의 판정으로 계산할 조건(바깥 AND, 안쪽 OR). 빈 배열이면 LLM이 직접 판정';

-- ── 옛 speaking_v0(0044) 6개를 먼저 실제 시험 풀에서 뺀다 ──
-- 새로 넣을 speaking_v1도 같은 이미지/음성 경로(speaking-v0/...)를 그대로 쓰므로,
-- 이 UPDATE를 INSERT보다 반드시 먼저 실행해야 한다 — 순서를 바꾸면 asset path로
-- 매칭하는 이 조건이 방금 넣은 새 행까지 같이 used=false로 꺼버린다.
update tb_question
set used = false
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

-- ── speaking_v1 문항 6개 삽입 ──
with inserted as (
  insert into tb_question (part, content, used) values
  (
    'READ_AND_EXPLAIN',
    '{
      "preparationSeconds": 70,
      "responseSeconds": 80,
      "guideTexts": ["80초 동안 말할 수 있습니다."],
      "instruction": "이 표지는 무슨 의미입니까? 말로 설명하세요.",
      "imageUrl": "speaking-v0/read-and-explain-02.png",
      "sceneDescription": "초록 바탕 직사각형 표지. 왼쪽에 흰 테두리 빨간 원 안에 위쪽 화살표, 오른쪽에 흰 글자 비상대피로.",
      "itemType": "sign_description",
      "expectedRegister": "any",
      "referenceKeywords": ["비상", "대피", "화살표", "출구", "나가", "위험"]
    }'::jsonb,
    true
  ),
  (
    'READ_AND_EXPLAIN',
    '{
      "preparationSeconds": 70,
      "responseSeconds": 80,
      "guideTexts": ["80초 동안 말할 수 있습니다."],
      "instruction": "이 표지는 무슨 의미입니까? 말로 설명하세요.",
      "imageUrl": "speaking-v0/read-and-explain-01.png",
      "sceneDescription": "흰 바탕 입간판. 위에 파란 글자 근로자, 가운데 큰 분홍 글자 쉼터, 아래 작은 글자 충분한 휴식은 안전의 또다른 준비 입니다. 공사장 자갈 바닥 배경.",
      "itemType": "sign_description",
      "expectedRegister": "any",
      "referenceKeywords": ["근로자", "쉼터", "휴식", "쉬", "안전"]
    }'::jsonb,
    true
  ),
  (
    'SITUATION_DESCRIPTION',
    '{
      "preparationSeconds": 40,
      "responseSeconds": 60,
      "guideTexts": ["60초 동안 말할 수 있습니다."],
      "instruction": "사진 속 사람이 지금 무엇을 하고 있는지 묘사하세요.",
      "imageUrl": "speaking-v0/situation-description-01.png",
      "sceneDescription": "공사 현장. 주황 안전모·안전대(형광 하네스)·장갑을 착용한 남성 작업자가 나무 작업대 위 나무판을 왼손으로 누르고 오른손 망치로 두드리고(못 박고) 있다. 뒤에 콘크리트 펌프카·트럭·철근 구조물.",
      "itemType": "picture_description",
      "expectedRegister": "any",
      "referenceKeywords": ["망치", "작업자", "안전모", "나무", "두드리", "장갑"]
    }'::jsonb,
    true
  ),
  (
    'SITUATION_DESCRIPTION',
    '{
      "preparationSeconds": 40,
      "responseSeconds": 60,
      "guideTexts": ["60초 동안 말할 수 있습니다."],
      "instruction": "사진 속 사람은 당신과 같이 일하는 동료입니다. 동료에게 무엇이 위험한지 알려주고, 어떻게 해야 하는지 말하세요.",
      "imageUrl": "speaking-v0/situation-description-02.png",
      "sceneDescription": "거푸집(합판 벽) 공사 현장. 안전모를 쓰지 않은(맨머리) 남성 작업자가 회색 긴팔·공구벨트·안전대 차림으로 알루미늄 사다리를 손으로 들고 세우고 있다. 아직 사다리에 올라가지는 않았다. 주변에 철제 지지대·높은 벽.",
      "itemType": "hazard_warning",
      "expectedRegister": "polite",
      "referenceKeywords": ["안전모", "사다리", "위험", "다치", "떨어지", "쓰세요"]
    }'::jsonb,
    true
  ),
  (
    'ANSWER_QUESTION',
    '{
      "preparationSeconds": 20,
      "responseSeconds": 30,
      "guideTexts": ["질문을 잘 듣고 대답하세요.", "30초 동안 답변할 수 있습니다."],
      "instruction": "오늘 회사에 늦으셨군요. 왜 늦으셨나요?",
      "audioUrl": "speaking-v0/answer-question-01.wav",
      "itemType": "answer_question",
      "expectedRegister": "polite",
      "referenceKeywords": ["늦", "죄송", "버스", "막혀", "그래서", "다음"]
    }'::jsonb,
    true
  ),
  (
    'ANSWER_QUESTION',
    '{
      "preparationSeconds": 20,
      "responseSeconds": 30,
      "guideTexts": ["질문을 잘 듣고 대답하세요.", "30초 동안 답변할 수 있습니다."],
      "instruction": "손이 못에 찔렸을 때는 어떻게 해야 하나요?",
      "audioUrl": "speaking-v0/answer-question-02.wav",
      "itemType": "answer_question",
      "expectedRegister": "any",
      "referenceKeywords": ["병원", "다쳤", "피", "소독", "말해", "멈추"]
    }'::jsonb,
    true
  )
  returning question_id, content ->> 'imageUrl' as image_url, content ->> 'audioUrl' as audio_url
)
insert into tb_question_checklist_item (question_id, code, description, weight, display_order, description_en, requires)
select question_id, code, description, weight, display_order, description_en, requires::jsonb
from inserted
join (
  values
    -- SPK-101 → read-and-explain-02.png (비상대피로)
    ('speaking-v0/read-and-explain-02.png', 'c1', '표지에 적힌 글자(비상 / 대피 / 비상대피로) 중 하나 이상을 말했는가', 1.5, 0, 'Say a word written on the sign, such as emergency or evacuation.', '[]'),
    ('speaking-v0/read-and-explain-02.png', 'c2', '표지의 시각 요소(화살표, 원, 색깔) 중 하나 이상을 언급했는가', 1.0, 1, 'Describe what you see on the sign, such as the arrow, the circle, or the color.', '[]'),
    ('speaking-v0/read-and-explain-02.png', 'c3', '길·통로·출구·나가는 곳 등 이동 경로를 뜻하는 표현을 사용했는가', 1.5, 2, 'Use a word for a way out, such as road, path, or exit.', '[]'),
    ('speaking-v0/read-and-explain-02.png', 'c4', '위급 상황(불·화재·지진·사고·위험 등)을 하나 이상 언급했는가', 1.5, 3, 'Name a dangerous situation, such as a fire, an earthquake, or an accident.', '[]'),
    ('speaking-v0/read-and-explain-02.png', 'c5', '화살표가 가리키는 방향(위쪽·앞쪽·직진 등)을 말했는가', 1.0, 4, 'Say which way the arrow points, such as up or straight ahead.', '[]'),
    ('speaking-v0/read-and-explain-02.png', 'c6', '사람이 해야 할 행동을 동사로 말했는가 (나가다·가다·따라가다·피하다·대피하다 등)', 1.0, 5, 'Say what people must do, using a verb like go out or escape.', '[]'),
    ('speaking-v0/read-and-explain-02.png', 'c7', '위급 상황과 이동(대피)을 하나의 문장 안에서 연결해 말했는가', 1.0, 6, 'In one sentence, connect the emergency and going out.', '[]'),
    ('speaking-v0/read-and-explain-02.png', 'c8', '표지의 의미를 설명하는 형식으로 진술했는가 (…라는 뜻이에요 / …를 알려주는 표지예요 등)', 1.0, 7, 'Explain the meaning of the sign, like this sign means or this sign tells you.', '[]'),
    ('speaking-v0/read-and-explain-02.png', 'c9', '[보너스] 비상 상황 + 대피 경로 + 방향 또는 행동, 세 요소를 모두 포함했는가', 0.5, 8, 'Say all three things: the emergency, the escape route, and the direction or action.', '[["c4"],["c3"],["c5","c6"]]'),

    -- SPK-102 → read-and-explain-01.png (근로자 쉼터)
    ('speaking-v0/read-and-explain-01.png', 'c1', '[최소기준] 한국어로 표지에 대해 무언가를 설명하려는 발화가 있는가', 0.5, 0, 'Say something in Korean about this sign.', '[]'),
    ('speaking-v0/read-and-explain-01.png', 'c2', '표지에 적힌 글자(근로자 / 쉼터) 중 하나 이상을 말했는가', 1.5, 1, 'Say a word written on the sign, such as worker or rest area.', '[]'),
    ('speaking-v0/read-and-explain-01.png', 'c3', '이 표지가 특정 장소를 가리킨다는 것을 나타내는 표현을 사용했는가 (여기, 이곳, 방, 곳, 자리 등)', 1.0, 2, 'Use a word that shows this is a place, such as here or room.', '[]'),
    ('speaking-v0/read-and-explain-01.png', 'c4', '휴식을 뜻하는 어휘를 사용했는가 (쉬다, 휴식, 쉼터, 잠깐 쉬다, 좀 쉬다 등)', 1.5, 3, 'Use a word about resting, such as rest or take a break.', '[]'),
    ('speaking-v0/read-and-explain-01.png', 'c5', '이 장소를 이용하는 대상이 일하는 사람임을 언급했는가 (근로자, 노동자, 일하는 사람, 우리 등)', 1.0, 4, 'Say who uses this place, such as workers or people who work here.', '[]'),
    ('speaking-v0/read-and-explain-01.png', 'c6', '그 장소에서 하는 행동을 동사로 말했는가 (쉬어요, 들어가요, 앉아요, 밥 먹어요, 물 마셔요 등)', 1.0, 5, 'Say what people do there, using a verb like rest, sit, or eat.', '[]'),
    ('speaking-v0/read-and-explain-01.png', 'c7', '안전과 관련된 표현을 언급했는가 (안전, 사고, 다치다, 위험 등)', 1.0, 6, 'Use a word about safety, such as safety, accident, or danger.', '[]'),
    ('speaking-v0/read-and-explain-01.png', 'c8', '휴식과 안전의 관계를 하나의 문장 안에서 연결해 말했는가 (예: 쉬면 안전해요, 안 쉬면 다쳐요)', 1.0, 7, 'In one sentence, connect resting and safety.', '[]'),
    ('speaking-v0/read-and-explain-01.png', 'c9', '표지의 의미를 설명하는 형식으로 진술했는가 (…라는 뜻이에요 / …를 알려주는 표지예요 등)', 1.0, 8, 'Explain the meaning of the sign, like this sign means or this sign tells you.', '[]'),
    ('speaking-v0/read-and-explain-01.png', 'c10', '[보너스] 대상(일하는 사람) + 기능(쉬는 곳·휴식) + 이유(안전), 세 요소를 모두 포함했는가', 0.5, 9, 'Say all three things: who uses it, what it is for, and why it helps.', '[["c5"],["c4"],["c7"]]'),

    -- SPK-103 → situation-description-01.png (망치질하는 작업자)
    ('speaking-v0/situation-description-01.png', 'c1', '[최소기준] 사진 속 장면에 대한 정보를 하나라도 말했는가', 0.5, 0, 'Say at least one thing about the picture.', '[]'),
    ('speaking-v0/situation-description-01.png', 'c2', '사진 속 인물을 가리키는 표현을 사용했는가 (사람, 남자, 아저씨, 작업자, 근로자 등)', 1.0, 1, 'Say who is in the picture, such as a man or a worker.', '[]'),
    ('speaking-v0/situation-description-01.png', 'c3', '그 인물이 일이나 작업을 하고 있다는 것을 나타내는 표현을 사용했는가 (일해요, 작업해요, 공사해요 등)', 1.0, 2, 'Say that he is working, using a word like work.', '[]'),
    ('speaking-v0/situation-description-01.png', 'c4', '인물이 손에 들고 사용하는 도구나 물건을 언급했는가 (망치, 공구, 연장, 이거 등)', 1.0, 3, 'Say what he is holding in his hand, such as a tool.', '[]'),
    ('speaking-v0/situation-description-01.png', 'c5', '인물이 착용한 안전 장비를 하나 이상 언급했는가 (안전모, 헬멧, 모자, 장갑, 안전벨트, 안전대 등)', 1.0, 4, 'Name one safety item he is wearing, such as a helmet or gloves.', '[]'),
    ('speaking-v0/situation-description-01.png', 'c6', '도구를 망치라는 단어로 정확히 지칭했는가', 1.0, 5, 'Use the exact word for the tool: hammer.', '[]'),
    ('speaking-v0/situation-description-01.png', 'c7', '두드리거나 치는 동작을 나타내는 동사를 사용했는가 (때리다, 치다, 두드리다, 박다, 못 박다 등)', 1.5, 6, 'Say what he is doing with the tool, such as hitting or hammering.', '[]'),
    ('speaking-v0/situation-description-01.png', 'c8', '작업의 대상이 되는 물체를 언급했는가 (나무, 나무판, 판, 목재, 책상, 작업대 등)', 1.5, 7, 'Say what he is working on, such as wood or a board.', '[]'),
    ('speaking-v0/situation-description-01.png', 'c9', '인물의 자세나 반대쪽 손의 동작을 언급했는가 (누르고 있다, 잡고 있다, 서 있다, 고개를 숙이고 있다, 내려다보고 있다 등)', 1.0, 8, 'Say how he stands or what his other hand does, such as holding the board down.', '[]'),
    ('speaking-v0/situation-description-01.png', 'c10', '[보너스] 인물 + 도구 + 대상 + 두드리는 행위, 네 요소를 모두 포함했는가', 0.5, 9, 'Say all four things: the person, the tool, the object, and the hitting action.', '[["c2"],["c4"],["c8"],["c7"]]'),

    -- SPK-104 → situation-description-02.png (안전모 없이 사다리)
    ('speaking-v0/situation-description-02.png', 'c1', '[최소기준] 사진 속 상황에 대한 정보를 하나라도 말했는가', 0.5, 0, 'Say at least one thing about what you see.', '[]'),
    ('speaking-v0/situation-description-02.png', 'c2', '위험이나 주의를 나타내는 표현을 사용했는가 (위험해요, 안 돼요, 조심하세요, 큰일 나요 등)', 1.0, 1, 'Warn him with a word like dangerous or be careful.', '[]'),
    ('speaking-v0/situation-description-02.png', 'c3', '안전모를 가리키는 표현을 사용했는가 (안전모, 헬멧, 모자, 머리에 쓰는 거 등)', 1.0, 2, 'Use a word for the safety helmet, such as helmet or hard hat.', '[]'),
    ('speaking-v0/situation-description-02.png', 'c4', '안전모를 착용하지 않은 상태임을 서술했는가 (안 썼어요, 없어요, 머리에 아무것도 없어요 등)', 1.5, 3, 'Say that he is not wearing a helmet.', '[]'),
    ('speaking-v0/situation-description-02.png', 'c5', '사다리를 언급했는가 (사다리, 계단, 올라가는 거 등)', 1.0, 4, 'Say that he has a ladder.', '[]'),
    ('speaking-v0/situation-description-02.png', 'c6', '사다리에 올라가는 것(앞으로 할 행동)의 위험을 언급했는가 (올라가면 위험해요, 올라가지 마세요, 그렇게 올라가면 떨어져요 등)', 1.0, 5, 'Tell him it is dangerous to climb the ladder like this.', '[]'),
    ('speaking-v0/situation-description-02.png', 'c7', '일어날 수 있는 사고나 그 결과를 언급했는가 (떨어져요, 넘어져요, 다쳐요, 머리 다쳐요, 사고 나요 등)', 1.0, 6, 'Say what can happen, such as falling down or getting hurt.', '[]'),
    ('speaking-v0/situation-description-02.png', 'c8', '안전모를 착용하라는 조치를 말했는가 (안전모 쓰세요, 헬멧 써요, 안전모 필요해요 등)', 1.5, 7, 'Tell him to put on a safety helmet.', '[]'),
    ('speaking-v0/situation-description-02.png', 'c9', '안전모 착용 외의 구체적인 조치나 행동을 말했는가 (내려오세요, 잠깐 멈추세요, 안전벨트 거세요, 사다리 잡아주세요, 사다리 고정하세요 등)', 1.0, 8, 'Tell him one more thing to do, such as stop, come down, or hold the ladder.', '[]'),
    ('speaking-v0/situation-description-02.png', 'c10', '[보너스] 위험 요소를 알리는 내용과 조치를 제안하는 내용을 모두 포함했는가', 0.5, 9, 'Do both: tell him the danger and tell him what to do.', '[["c2","c4","c6","c7"],["c8","c9"]]'),

    -- SPK-105 → answer-question-01.wav (지각 사유)
    ('speaking-v0/answer-question-01.wav', 'c1', '[최소기준] 질문에 대해 한국어로 대답하려는 발화가 있는가', 0.5, 0, 'Answer the question in Korean.', '[]'),
    ('speaking-v0/answer-question-01.wav', 'c2', '늦은 사실을 인정하거나 언급했는가 (늦었어요, 지각했어요, 미안해요, 죄송해요 등)', 1.0, 1, 'Say that you were late.', '[]'),
    ('speaking-v0/answer-question-01.wav', 'c3', '늦은 이유를 하나라도 말했는가 (차가 막혀서, 늦게 일어나서, 버스를 놓쳐서, 아파서 등)', 1.5, 2, 'Give a reason for being late.', '[]'),
    ('speaking-v0/answer-question-01.wav', 'c4', '이유가 되는 사건이나 상황을 구체적으로 설명했는가 (알람이 안 울렸어요, 버스가 안 왔어요, 배가 아팠어요 등 상황 서술)', 1.5, 3, 'Explain what happened, such as your alarm did not ring.', '[]'),
    ('speaking-v0/answer-question-01.wav', 'c5', '시간과 관련된 정보를 언급했는가 (몇 시, 아침에, 30분, 늦게, 일찍 등)', 1.0, 4, 'Say something about time, such as this morning or thirty minutes.', '[]'),
    ('speaking-v0/answer-question-01.wav', 'c6', '장소나 이동 수단을 언급했는가 (집, 회사, 버스, 지하철, 길, 정류장 등)', 1.0, 5, 'Say a place or how you travel, such as the bus or the station.', '[]'),
    ('speaking-v0/answer-question-01.wav', 'c7', '원인과 결과의 관계를 나타내는 연결 표현을 사용했는가 (그래서, -어서, -기 때문에, -니까 등)', 1.0, 6, 'Connect the cause and the result with a word like so or because.', '[]'),
    ('speaking-v0/answer-question-01.wav', 'c8', '앞으로의 행동이나 다짐을 말했는가 (다음부터 일찍 올게요, 조심하겠습니다, 안 늦을게요 등)', 1.0, 7, 'Say what you will do next time, such as I will come early.', '[]'),
    ('speaking-v0/answer-question-01.wav', 'c9', '사과하거나 양해를 구하는 표현을 사용했는가 (죄송합니다, 미안합니다, 죄송해요 등)', 1.0, 8, 'Say sorry to your boss.', '[]'),
    ('speaking-v0/answer-question-01.wav', 'c10', '[보너스] 늦은 사실 + 이유 + 사과 또는 앞으로의 다짐, 세 요소를 모두 포함했는가', 0.5, 9, 'Say all three things: that you were late, the reason, and an apology or a promise.', '[["c2"],["c3"],["c8","c9"]]'),

    -- SPK-106 → answer-question-02.wav (못에 찔림)
    ('speaking-v0/answer-question-02.wav', 'c1', '[최소기준] 질문에 대해 한국어로 대답하려는 발화가 있는가', 0.5, 0, 'Answer the question in Korean.', '[]'),
    ('speaking-v0/answer-question-02.wav', 'c2', '다쳤을 때 해야 할 행동을 하나라도 말했는가 (병원 가요, 약 발라요, 말해요, 씻어요 등)', 1.0, 1, 'Say one thing you must do when you are hurt.', '[]'),
    ('speaking-v0/answer-question-02.wav', 'c3', '작업을 멈추거나 그 자리를 벗어나는 행동을 언급했는가 (일 그만해요, 멈춰요, 나와요, 쉬어요 등)', 1.0, 2, 'Say that you stop working or leave the place.', '[]'),
    ('speaking-v0/answer-question-02.wav', 'c4', '다른 사람에게 알리는 행동을 언급했는가 (관리자한테 말해요, 반장님한테 알려요, 동료를 불러요, 신고해요 등)', 1.5, 3, 'Say that you tell someone, such as your manager.', '[]'),
    ('speaking-v0/answer-question-02.wav', 'c5', '상처를 처치하는 구체적인 행동을 언급했는가 (씻어요, 소독해요, 약 발라요, 밴드 붙여요, 피 닦아요 등)', 1.5, 4, 'Say how you take care of the wound, such as washing it or putting on a bandage.', '[]'),
    ('speaking-v0/answer-question-02.wav', 'c6', '병원이나 의료기관에 가는 것을 언급했는가 (병원, 의무실, 보건실, 의사, 119, 구급차 등)', 1.0, 5, 'Say that you go to a hospital or call for help.', '[]'),
    ('speaking-v0/answer-question-02.wav', 'c7', '상처나 부상의 상태를 나타내는 표현을 사용했는가 (피가 나요, 아파요, 상처, 다쳤어요, 부었어요 등)', 1.0, 6, 'Describe the injury, such as it is bleeding or it hurts.', '[]'),
    ('speaking-v0/answer-question-02.wav', 'c8', '하지 말아야 할 행동이나 주의사항을 언급했는가 (계속 일하면 안 돼요, 손으로 만지면 안 돼요, 그냥 두면 안 돼요 등)', 1.0, 7, 'Say what you must not do, such as keep working.', '[]'),
    ('speaking-v0/answer-question-02.wav', 'c9', '방치했을 때 생길 수 있는 결과를 언급했는가 (덧나요, 세균, 감염, 병 나요, 더 아파요, 파상풍 등)', 1.0, 8, 'Say what can happen if you do nothing, such as an infection.', '[]'),
    ('speaking-v0/answer-question-02.wav', 'c10', '[보너스] 즉시 취할 행동 + 알리거나 치료받는 행동, 두 축을 모두 포함했는가', 0.5, 9, 'Do both: say what you do right away and say that you tell someone or get treatment.', '[["c3","c5"],["c4","c6"]]')
) as checklist (asset_path, code, description, weight, display_order, description_en, requires)
  on checklist.asset_path = coalesce(inserted.image_url, inserted.audio_url);
