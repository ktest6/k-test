import { Inject, Injectable } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { Document } from '../../domain/entities/document.entity';
import {
  DOCUMENT_REPOSITORY,
  DocumentRepository,
} from '../../domain/document.repository.interface';
import {
  DOCUMENT_UPLOADED_EVENT,
  DocumentUploadedEvent,
} from '../../domain/events/document-uploaded.event';
import { UploadDocumentDto } from '../dto/upload-document.dto';

@Injectable()
export class DocumentService {
  constructor(
    @Inject(DOCUMENT_REPOSITORY) private readonly documentRepository: DocumentRepository,
    private readonly eventEmitter: EventEmitter2,
  ) {}

  async upload(uploaderId: string, dto: UploadDocumentDto): Promise<Document> {
    const fileName = dto.fileName ?? dto.filePath.split('/').pop() ?? dto.filePath;
    const examId = dto.examId;

    const document = await this.documentRepository.create({
      filePath: dto.filePath,
      fileName,
      uploadedBy: uploaderId,
      metadata: examId !== undefined ? { examId } : undefined,
    });

    this.eventEmitter.emit(
      DOCUMENT_UPLOADED_EVENT,
      new DocumentUploadedEvent(document.id, document.filePath, document.fileName, examId),
    );

    return document;
  }

  async findById(id: string): Promise<Document> {
    const document = await this.documentRepository.findById(id);
    if (!document) {
      throw new NotFoundDomainException(`문서(${id})를 찾을 수 없습니다.`);
    }
    return document;
  }
}
