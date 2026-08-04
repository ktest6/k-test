export const SCORING_PROVIDER = Symbol('SCORING_PROVIDER');

export interface ScoreChecklistItemInput {
  /** assessment 쪽 규격 — 우리 tb_question_checklist_item.code에 해당 (예: "c1"). */
  id: string;
  description: string;
  weight: number;
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
