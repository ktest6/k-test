/** tb_question.content의 실제 저장 형태 그대로 — AI가 생성한 원본 항목 하나. */
export interface QuestionContent {
  item_id: string;
  prompt: string;
  expected_register: string;
  reference_keywords: string[];
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
    readonly part: string,
    readonly content: QuestionContent,
    /** 이 문항을 생성한 서류. 서류 없이 만들어졌으면 NULL. */
    readonly documentId: string | null,
    readonly checklistItems: QuestionChecklistItem[],
    readonly createdAt: Date,
  ) {}
}
