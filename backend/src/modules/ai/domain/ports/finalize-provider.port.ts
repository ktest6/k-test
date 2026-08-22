export const FINALIZE_PROVIDER = Symbol('FINALIZE_PROVIDER');

export interface FinalizeExpectedItemInput {
  itemId: string;
  mode: 'writing' | 'speaking';
}

export interface FinalizeSessionInput {
  sessionId: string;
  candidateId: string;
  /** 이 세션에서 실제로 채점된 /score 응답들을 가공 없이 그대로 담는다. */
  items: Record<string, unknown>[];
  /** 이 세션에 배정된 문항 전체 — items에 없는 것은 assessment가 자동으로 missing으로 잡는다(스킵 등). */
  expectedItems: FinalizeExpectedItemInput[];
}

/**
 * 시험 전체 최종 등급을 산출하는 외부 assessment 서비스(POST /finalize) 추상화.
 * 응답 형식은 서비스가 자유롭게 정하므로(raw_response로 그대로 저장) 여기서는
 * 파싱하지 않고 그대로 반환한다.
 */
export interface FinalizeProviderPort {
  finalize(input: FinalizeSessionInput): Promise<Record<string, unknown>>;
}
