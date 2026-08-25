import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { operationFailed } from '../../../../common/exceptions/error-messages';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { Document, DocumentMetadata } from '../../domain/entities/document.entity';
import { DocumentStatus } from '../../domain/enums/document-status.enum';
import {
  CreateDocumentInput,
  DocumentRepository,
} from '../../domain/document.repository.interface';

const TABLE = 'tb_document';

interface DocumentRow {
  document_id: number;
  file_path: string;
  file_name: string;
  uploaded_by: number | null;
  status: DocumentStatus;
  metadata: DocumentMetadata | null;
  error_message: string | null;
  created_at: string;
}

function toDomain(row: DocumentRow): Document {
  return new Document(
    String(row.document_id),
    row.file_path,
    row.file_name,
    row.uploaded_by !== null ? String(row.uploaded_by) : null,
    row.status,
    row.metadata,
    row.error_message,
    new Date(row.created_at),
  );
}

@Injectable()
export class SupabaseDocumentRepository implements DocumentRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async create(input: CreateDocumentInput): Promise<Document> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .insert({
        file_path: input.filePath,
        file_name: input.fileName,
        uploaded_by: Number(input.uploadedBy),
        metadata: input.metadata ?? null,
      })
      .select()
      .single<DocumentRow>();

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? operationFailed('upload the document'));
    }
    return toDomain(data);
  }

  async findById(id: string): Promise<Document | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('document_id', Number(id))
      .maybeSingle<DocumentRow>();
    return data ? toDomain(data) : null;
  }

  async markProcessing(id: string): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    await client
      .from(TABLE)
      .update({ status: DocumentStatus.PROCESSING })
      .eq('document_id', Number(id));
  }

  async markCompleted(id: string, metadata: DocumentMetadata): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    await client
      .from(TABLE)
      .update({ status: DocumentStatus.COMPLETED, metadata })
      .eq('document_id', Number(id));
  }

  async markFailed(id: string, errorMessage: string): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    await client
      .from(TABLE)
      .update({ status: DocumentStatus.FAILED, error_message: errorMessage })
      .eq('document_id', Number(id));
  }
}
