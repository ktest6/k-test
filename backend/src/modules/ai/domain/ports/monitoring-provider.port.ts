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
  /** 사전 캘리브레이션 결과가 있을 때만 값 있음 — 둘 다 있어야 시선 판정에 반영된다. */
  eyeYawCenter?: number;
  eyePitchCenter?: number;
  /** 직전 analyze 호출에서 돌려받은 연속 시선 상태 — 첫 프레임이거나 저장된 상태가 없으면 생략. */
  previousGazeState?: Record<string, unknown>;
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
  /** FastAPI가 계산한 다음 연속 시선 상태 — 세션에 저장해뒀다가 다음 analyze 요청의 previousGazeState로 그대로 돌려줘야 한다. */
  gazeState: Record<string, unknown> | null;
  /** 응답 원문 그대로 — 감사/디버깅용으로 meta에 저장한다. */
  raw: Record<string, unknown>;
}

export interface CalibrateGazeInput {
  examId: string;
  examineeId: string;
  /** 화면 중앙을 응시한 이미지 여러 장. */
  calibrationImages: MonitoringImageInput[];
}

export interface CalibrateGazeResult {
  calibrated: boolean;
  sampleCount: number;
  eyeYawCenter: number;
  eyePitchCenter: number;
}

/**
 * 웹캠 프레임 하나를 분석해 얼굴/시선/객체/동일인 여부와 의심 행동을
 * 판정하는 외부 부정행위 감지 서비스 추상화(도영님 담당). calibrate는
 * 시험 시작 전 화면 중앙 응시 이미지로 개인별 시선 기준값을 뽑는 별도
 * 엔드포인트지만, 같은 서비스(같은 base URL)라 이 포트에 함께 둔다.
 */
export interface MonitoringProviderPort {
  analyze(input: AnalyzeFrameInput): Promise<AnalyzeFrameResult>;
  calibrate(input: CalibrateGazeInput): Promise<CalibrateGazeResult>;
}
