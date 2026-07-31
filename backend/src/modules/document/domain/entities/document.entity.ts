import { DocumentStatus } from '../enums/document-status.enum';

export interface DocumentMetadata {
  /** 문항 생성 배치 버전 (예: writing_v0). 생성 완료 시점에 채워진다. */
  version?: string;
  /** 문항 대분류 (writing, speaking 등). 생성 완료 시점에 채워진다. */
  mode?: string;
  note?: string;
  /** 업로드 시점에 회차를 미리 지정했다면 여기 보관 — 실제 회차 배정은 이 모듈 범위 밖의 별도 기능. */
  examId?: string;
}

export class Document {
  constructor(
    readonly id: string,
    readonly filePath: string,
    readonly fileName: string,
    /** 시스템이 생성한 경우 등은 NULL 허용. */
    readonly uploadedBy: string | null,
    readonly status: DocumentStatus,
    readonly metadata: DocumentMetadata | null,
    readonly errorMessage: string | null,
    readonly createdAt: Date,
  ) {}
}
