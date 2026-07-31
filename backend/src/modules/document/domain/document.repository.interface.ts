import { Document, DocumentMetadata } from './entities/document.entity';

export interface CreateDocumentInput {
  filePath: string;
  fileName: string;
  uploadedBy: string;
  metadata?: DocumentMetadata;
}

export const DOCUMENT_REPOSITORY = Symbol('DOCUMENT_REPOSITORY');

export interface DocumentRepository {
  create(input: CreateDocumentInput): Promise<Document>;
  findById(id: string): Promise<Document | null>;
  markProcessing(id: string): Promise<void>;
  /** metadata는 통째로 덮어쓴다 — 호출하는 쪽이 기존 값(예: examId)까지 포함해 완성된 값을 넘긴다. */
  markCompleted(id: string, metadata: DocumentMetadata): Promise<void>;
  markFailed(id: string, errorMessage: string): Promise<void>;
}
