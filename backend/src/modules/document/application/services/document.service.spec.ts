import { EventEmitter2 } from '@nestjs/event-emitter';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { Document } from '../../domain/entities/document.entity';
import { DocumentStatus } from '../../domain/enums/document-status.enum';
import { DocumentRepository } from '../../domain/document.repository.interface';
import { DOCUMENT_UPLOADED_EVENT } from '../../domain/events/document-uploaded.event';
import { UploadDocumentDto } from '../dto/upload-document.dto';
import { DocumentService } from './document.service';

function buildDocument(
  overrides: Partial<{ metadata: Record<string, unknown> | null }> = {},
): Document {
  return new Document(
    '1',
    'documents/2026/writing-source.pdf',
    'writing-source.pdf',
    '1',
    DocumentStatus.UPLOADED,
    overrides.metadata ?? null,
    null,
    new Date(),
  );
}

function buildRepository(overrides: Partial<DocumentRepository> = {}) {
  return {
    create: jest.fn().mockResolvedValue(buildDocument()),
    findById: jest.fn().mockResolvedValue(null),
    markProcessing: jest.fn(),
    markCompleted: jest.fn(),
    markFailed: jest.fn(),
    ...overrides,
  };
}

describe('DocumentService.upload', () => {
  it('creates the document, derives fileName from filePath when omitted, and emits document.uploaded', async () => {
    const created = buildDocument();
    const repository = buildRepository({ create: jest.fn().mockResolvedValue(created) });
    const emit = jest.fn();
    const eventEmitter = { emit } as unknown as EventEmitter2;
    const service = new DocumentService(repository, eventEmitter);
    const dto: UploadDocumentDto = { filePath: 'documents/2026/writing-source.pdf' };

    const result = await service.upload('1', dto);

    expect(repository.create).toHaveBeenCalledWith({
      filePath: 'documents/2026/writing-source.pdf',
      fileName: 'writing-source.pdf',
      uploadedBy: '1',
      metadata: undefined,
    });
    expect(emit).toHaveBeenCalledWith(
      DOCUMENT_UPLOADED_EVENT,
      expect.objectContaining({
        documentId: '1',
        filePath: created.filePath,
        fileName: created.fileName,
      }),
    );
    expect(result).toBe(created);
  });

  it('uses the provided fileName instead of deriving one', async () => {
    const repository = buildRepository();
    const eventEmitter = { emit: jest.fn() } as unknown as EventEmitter2;
    const service = new DocumentService(repository, eventEmitter);
    const dto: UploadDocumentDto = { filePath: 'documents/x.pdf', fileName: 'custom.pdf' };

    await service.upload('1', dto);

    expect(repository.create).toHaveBeenCalledWith(
      expect.objectContaining({ fileName: 'custom.pdf' }),
    );
  });

  it('stashes examId into metadata and forwards it on the emitted event when provided', async () => {
    const repository = buildRepository();
    const emit = jest.fn();
    const eventEmitter = { emit } as unknown as EventEmitter2;
    const service = new DocumentService(repository, eventEmitter);
    const dto: UploadDocumentDto = { filePath: 'documents/x.pdf', examId: 2 };

    await service.upload('1', dto);

    expect(repository.create).toHaveBeenCalledWith(
      expect.objectContaining({ metadata: { examId: '2' } }),
    );
    expect(emit).toHaveBeenCalledWith(
      DOCUMENT_UPLOADED_EVENT,
      expect.objectContaining({ examId: '2' }),
    );
  });
});

describe('DocumentService.findById', () => {
  it('throws NotFoundDomainException when the document does not exist', async () => {
    const repository = buildRepository();
    const eventEmitter = {} as unknown as EventEmitter2;
    const service = new DocumentService(repository, eventEmitter);

    await expect(service.findById('1')).rejects.toThrow(NotFoundDomainException);
  });

  it('returns the document when found', async () => {
    const document = buildDocument();
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(document) });
    const eventEmitter = {} as unknown as EventEmitter2;
    const service = new DocumentService(repository, eventEmitter);

    const result = await service.findById('1');

    expect(result).toBe(document);
  });
});
