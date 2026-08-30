import { QuestionSectionType } from '../enums/question-section-type.enum';

/**
 * tb_question.content의 실제 저장 형태 — 듣기/말하기 3유형(QuestionSectionType) 공용 구조.
 * 유형마다 쓰는 필드가 다르므로 유형별 필드는 전부 optional이다.
 */
export interface QuestionContent {
  /** 준비시간(초). */
  preparationSeconds: number;
  /** 응답시간(초). */
  responseSeconds: number;
  /** 유형별 고정 안내문구. 유형1·2는 1개, 유형3(지시문+안내문구)은 2개. */
  guideTexts: string[];

  /** 지시문 — SITUATION_DESCRIPTION, READ_AND_EXPLAIN 전용(매 문항마다 다름). */
  instruction?: string;
  /** 상황 묘사 이미지 — SITUATION_DESCRIPTION 전용. */
  imageUrl?: string;
  /** 안전수칙 타이틀 — READ_AND_EXPLAIN 전용. */
  safetyRulesTitle?: string;
  /** 안전수칙 항목 리스트(가변 개수) — READ_AND_EXPLAIN 전용. */
  safetyRules?: string[];
  /** 질문 음성 파일 경로 — ANSWER_QUESTION 전용. 응시자 답안 음성과는 별개(문항 자체가 들려주는 음성). */
  audioUrl?: string;

  /**
   * 채점 LLM에게 그림 내용을 글로 전달하는 필드(assessment ItemInfo.scene_description과 매핑) —
   * 채점 AI는 imageUrl을 보지 못하므로, 시각 요소를 판정하는 체크리스트 항목이 있으면 필수.
   * 응시자에게는 노출하지 않는다(SessionQuestionResponseDto에 없음).
   */
  sceneDescription?: string;
  /** assessment ItemInfo.item_type과 매핑되는 문항 세부 유형(예: sign_description, hazard_warning). */
  itemType?: string;
  /** LLM을 못 쓸 때의 임시 대체 판정용 핵심어(assessment ItemInfo.reference_keywords). */
  referenceKeywords?: string[];
  /**
   * 이 문항이 요구하는 말투(assessment ItemInfo.expected_register: formal/polite/any) —
   * 없으면 채점 요청에서 가장 중립적인 'any'로 채운다.
   */
  expectedRegister?: string;
}

export interface QuestionChecklistItem {
  id: string;
  code: string;
  description: string;
  weight: number;
  displayOrder: number;
  /** 리포트 화면에 보여줄 영어 문장 — 채점에는 안 쓰인다(assessment ChecklistItem.description_en). */
  descriptionEn?: string;
  /**
   * 이 항목을 LLM에게 안 묻고 앞 항목들의 판정으로 계산할 조건(assessment ChecklistItem.requires).
   * 바깥 배열은 AND, 안쪽 배열은 OR — 예: [["c4"],["c3"],["c5","c6"]] = "c4 그리고 c3 그리고 (c5 또는 c6)".
   * 가리키는 code는 이 항목보다 앞에 있어야 한다(assessment 쪽 제약).
   */
  requires?: string[][];
}

/** 회차 배정은 tb_exam_question(별도 모듈)에서 관리한다 — 문항 하나가 여러 회차에 재사용될 수 있어 1:1로 안 둔다. */
export class Question {
  constructor(
    readonly id: string,
    readonly part: QuestionSectionType,
    readonly content: QuestionContent,
    /** 이 문항을 생성한 서류. 서류 없이 만들어졌으면 NULL. */
    readonly documentId: string | null,
    readonly checklistItems: QuestionChecklistItem[],
    readonly createdAt: Date,
  ) {}
}
