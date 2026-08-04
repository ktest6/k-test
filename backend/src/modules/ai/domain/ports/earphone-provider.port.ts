export const EARPHONE_PROVIDER = Symbol('EARPHONE_PROVIDER');

export interface EarphoneImageInput {
  buffer: Buffer;
  filename: string;
  contentType: string;
}

export interface DetectEarphoneInput {
  examId: string;
  examineeId: string;
  leftEarImage: EarphoneImageInput;
  rightEarImage: EarphoneImageInput;
}

export interface DetectEarphoneResult {
  /** 양쪽 귀를 종합한 최종 이어폰 탐지 여부. */
  earphoneDetected: boolean;
  leftEarDetected: boolean;
  rightEarDetected: boolean;
  /** AWS Rekognition label. 탐지 안 되면 null. */
  leftLabel: string | null;
  rightLabel: string | null;
  leftConfidence: number;
  rightConfidence: number;
  threshold: number;
  message: string;
}

/** 시험 시작 전 이어폰 착용 여부를 감지하는 외부 서비스 추상화(AWS Rekognition 기반, FastAPI). */
export interface EarphoneProviderPort {
  detect(input: DetectEarphoneInput): Promise<DetectEarphoneResult>;
}
