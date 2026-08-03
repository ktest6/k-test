export const MONITORING_PROVIDER = Symbol('MONITORING_PROVIDER');

export interface MonitoringImageInput {
  buffer: Buffer;
  filename: string;
  contentType: string;
}

export interface AnalyzeFrameInput {
  examId: string;
  examineeId: string;
  requestId: string;
  /** ISO 8601, 타임존 포함 (예: 2026-07-31T13:05:00+09:00). */
  capturedAt: string;
  elapsedMs: number;
  captureSequence: number;
  runIdentityCheck: boolean;
  currentImage: MonitoringImageInput;
  /** runIdentityCheck가 true일 때만 값 있음. */
  referenceImage?: MonitoringImageInput;
}

export type MonitoringSeverity = 'NORMAL' | 'LOW' | 'MEDIUM' | 'HIGH';
export type MonitoringDecision = 'NONE' | 'RECORD_EVENT' | 'CREATE_CLIP';

export interface MonitoringEventSummary {
  eventDetected: boolean;
  eventCount: number;
  severity: MonitoringSeverity;
  decision: MonitoringDecision;
  createClip: boolean;
}

export interface MonitoringDetectedEvent {
  eventType: string;
  details: Record<string, unknown>;
}

export interface AnalyzeFrameResult {
  eventSummary: MonitoringEventSummary;
  events: MonitoringDetectedEvent[];
  /** 응답 원문 그대로 — 감사/디버깅용으로 meta에 저장한다. */
  raw: Record<string, unknown>;
}

/**
 * 웹캠 프레임 하나를 분석해 얼굴/시선/객체/동일인 여부와 의심 행동을
 * 판정하는 외부 부정행위 감지 서비스 추상화(도영님 담당).
 */
export interface MonitoringProviderPort {
  analyze(input: AnalyzeFrameInput): Promise<AnalyzeFrameResult>;
}
