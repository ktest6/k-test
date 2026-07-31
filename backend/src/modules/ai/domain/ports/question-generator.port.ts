export const QUESTION_GENERATOR = Symbol('QUESTION_GENERATOR');

export interface GeneratedChecklistItem {
  id: string;
  description: string;
  weight: number;
}

export interface GeneratedQuestionItem {
  itemId: string;
  itemType: string;
  prompt: string;
  expectedRegister: string;
  checklist: GeneratedChecklistItem[];
  referenceKeywords: string[];
}

export interface GeneratedQuestionSet {
  version: string;
  mode: string;
  note: string;
  items: GeneratedQuestionItem[];
}

export interface GenerateQuestionsInput {
  documentId: string;
  filePath: string;
  fileName: string;
}

/**
 * 서류(원본 자료)를 문항 초안 세트로 변환하는 AI 제공자 추상화. 지금은
 * MockQuestionGeneratorAdapter가 고정 JSON을 반환하지만, 실제 AI 서비스가
 * 준비되면 이 Port를 구현하는 어댑터로 교체하면 된다 — 호출하는 쪽
 * (document 모듈의 DocumentUploadedListener)은 전혀 안 바뀐다.
 */
export interface QuestionGeneratorPort {
  generate(input: GenerateQuestionsInput): Promise<GeneratedQuestionSet>;
}
