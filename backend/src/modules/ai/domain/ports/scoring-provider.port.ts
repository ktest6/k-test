export const SCORING_PROVIDER = Symbol('SCORING_PROVIDER');

export interface ScoreChecklistItemInput {
  /** assessment 쪽 규격 — 우리 tb_question_checklist_item.code에 해당 (예: "c1"). */
  id: string;
  description: string;
  weight: number;
  /** 리포트 화면 표시용 영어 문장 — 채점에는 안 쓰인다. 없으면 안 보내도 된다. */
  descriptionEn?: string;
  /** 이 항목을 LLM 대신 앞 항목들의 판정으로 계산할 조건(AND of OR). 없으면 LLM이 직접 판정한다. */
  requires?: string[][];
}

export interface ScoreItemInput {
  /** 채점 대상 답안 ID. assessment의 submission_id로 그대로 전달된다. */
  answerId: string;
  answerType: 'TEXT' | 'AUDIO';
  /** TEXT 답안일 때만 값 있음. */
  contentText: string | null;
  /** AUDIO 답안일 때만 값 있음 — Storage 상의 경로(공개 URL 변환은 어댑터가 처리). */
  audioFileUrl: string | null;
  /** AUDIO 답안일 때만 값 있을 수 있음 — wav가 아닌 포맷은 이 값이 있어야 assessment 응답에 duration이 남는다. */
  durationMs: number | null;
  item: {
    itemId: string;
    prompt: string;
    expectedRegister: string;
    checklist: ScoreChecklistItemInput[];
    /** assessment ItemInfo.item_type — 없으면 assessment가 기본값(free_response)으로 처리. */
    itemType?: string;
    /** 채점 LLM이 이미지를 못 보므로, 그림 기반 문항이면 이 글 설명으로 대신 전달한다. */
    sceneDescription?: string;
    /** LLM을 못 쓸 때의 임시 대체 판정용 핵심어. */
    referenceKeywords?: string[];
  };
}

/**
 * writing/speaking 답안을 채점하는 외부 assessment 서비스 추상화.
 * 응답 형식은 서비스가 자유롭게 정하므로(raw_response로 그대로 저장) 여기서는
 * 파싱하지 않고 그대로 반환한다.
 */
export interface ScoringProviderPort {
  score(input: ScoreItemInput): Promise<Record<string, unknown>>;
}
