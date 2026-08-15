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
}

export interface QuestionChecklistItem {
  id: string;
  code: string;
  description: string;
  weight: number;
  displayOrder: number;
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
