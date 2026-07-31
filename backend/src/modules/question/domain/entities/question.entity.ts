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

export enum QuestionStatus {
  UNUSED = 'UNUSED',
  USED = 'USED',
}

export class Question {
  constructor(
    readonly id: string,
    readonly part: string,
    readonly content: QuestionContent,
    /** NULL이면 아직 회차 미배정 — 회차 배정은 이 모듈 범위 밖의 별도 기능. */
    readonly examId: string | null,
    /** 이 문항을 생성한 서류. 서류 없이 만들어졌으면 NULL. */
    readonly documentId: string | null,
    readonly status: QuestionStatus,
    readonly checklistItems: QuestionChecklistItem[],
    readonly createdAt: Date,
  ) {}
}
