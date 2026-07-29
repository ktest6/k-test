export const AI_PROVIDER = Symbol('AI_PROVIDER');

export interface AiProviderStatus {
  provider: string;
  available: boolean;
}

/**
 * Abstraction over whichever AI provider eventually backs this module
 * (grading assist, question generation, fraud-detection analysis, ...).
 * No concrete use-case is wired in yet — this is the extension point other
 * modules (Scoring, Identity Verification) attach to later.
 */
export interface AiProvider {
  getStatus(): Promise<AiProviderStatus>;
}
