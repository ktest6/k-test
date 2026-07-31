export const DOCUMENT_UPLOADED_EVENT = 'document.uploaded';

/**
 * document 모듈은 question 모듈을 직접 호출하지 않고 이 이벤트만 발행한다
 * (identity-verification/submission 간 결합과 동일한 패턴) — 문항 생성
 * 로직은 DocumentUploadedListener가 구독해서 처리한다.
 */
export class DocumentUploadedEvent {
  constructor(
    readonly documentId: string,
    readonly filePath: string,
    readonly fileName: string,
    /** 업로드 시점에 회차를 미리 지정한 경우에만 값 있음. */
    readonly examId?: string,
  ) {}
}
