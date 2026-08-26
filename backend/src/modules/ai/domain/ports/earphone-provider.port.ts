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
  /** 양쪽 귀를 종합한 최종 이어폰 탐지 여부. inspectionComplete가 true일 때만 신뢰할 수 있다. */
  earphoneDetected: boolean;
  leftEarDetected: boolean;
  rightEarDetected: boolean;
  /** AWS Rekognition label. 탐지 안 되면 null. */
  leftLabel: string | null;
  rightLabel: string | null;
  leftConfidence: number;
  rightConfidence: number;
  threshold: number;
  /**
   * 양쪽 귀가 보이는 자세에서 검사가 끝났는지 여부. false면 자세 문제로 판정
   * 자체가 불완전한 상태라 earphoneDetected 값을 신뢰할 수 없다 — 이때는
   * leftEarVisible/rightEarVisible을 보고 어느 쪽 귀를 다시 보여줘야 하는지
   * 안내해야 한다.
   */
  inspectionComplete: boolean;
  leftEarVisible: boolean;
  rightEarVisible: boolean;
  /** 얼굴 yaw(좌우 회전각). 자세 조건을 못 맞춰 측정 자체가 안 됐으면 null. */
  leftYaw: number | null;
  rightYaw: number | null;
  /** 귀 노출 여부를 판단하는 yaw 절댓값 기준. */
  yawThreshold: number;
  message: string;
}

/** 시험 시작 전 이어폰 착용 여부를 감지하는 외부 서비스 추상화(AWS Rekognition 기반, FastAPI). */
export interface EarphoneProviderPort {
  detect(input: DetectEarphoneInput): Promise<DetectEarphoneResult>;
}
