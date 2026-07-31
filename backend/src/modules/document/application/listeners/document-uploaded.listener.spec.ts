import {
  GeneratedQuestionSet,
  QuestionGeneratorPort,
} from '../../../ai/domain/ports/question-generator.port';
import { QuestionService } from '../../../question/application/services/question.service';
import { DocumentRepository } from '../../domain/document.repository.interface';
import { DocumentUploadedEvent } from '../../domain/events/document-uploaded.event';
import { DocumentUploadedListener } from './document-uploaded.listener';

function buildGeneratedSet(): GeneratedQuestionSet {
  return {
    version: 'writing_v0',
    mode: 'writing',
    note: '검수 완료',
    items: [
      {
        itemId: 'WRT-001',
        itemType: 'work_log',
        prompt: '작업일지를 쓰세요.',
        expectedRegister: 'formal',
        checklist: [{ id: 'c1', description: '작업 기록', weight: 1 }],
        referenceKeywords: ['작업'],
      },
    ],
  };
}

function buildRepository(overrides: Partial<DocumentRepository> = {}) {
  return {
    create: jest.fn(),
    findById: jest.fn(),
    markProcessing: jest.fn(),
    markCompleted: jest.fn(),
    markFailed: jest.fn(),
    ...overrides,
  };
}

describe('DocumentUploadedListener', () => {
  it('marks PROCESSING, generates questions, bulk-creates drafts, then marks COMPLETED with metadata', async () => {
    const generated = buildGeneratedSet();
    const generate = jest.fn().mockResolvedValue(generated);
    const questionGenerator = { generate } as unknown as QuestionGeneratorPort;
    const bulkCreateDrafts = jest.fn().mockResolvedValue([]);
    const questionService = { bulkCreateDrafts } as unknown as QuestionService;
    const repository = buildRepository();
    const listener = new DocumentUploadedListener(repository, questionGenerator, questionService);
    const event = new DocumentUploadedEvent('1', 'documents/x.pdf', 'x.pdf');

    await listener.handle(event);

    expect(repository.markProcessing).toHaveBeenCalledWith('1');
    expect(generate).toHaveBeenCalledWith({
      documentId: '1',
      filePath: 'documents/x.pdf',
      fileName: 'x.pdf',
    });
    expect(bulkCreateDrafts).toHaveBeenCalledWith('1', [
      {
        part: 'work_log',
        content: {
          item_id: 'WRT-001',
          prompt: '작업일지를 쓰세요.',
          expected_register: 'formal',
          reference_keywords: ['작업'],
        },
        checklist: [{ code: 'c1', description: '작업 기록', weight: 1 }],
      },
    ]);
    expect(repository.markCompleted).toHaveBeenCalledWith('1', {
      version: 'writing_v0',
      mode: 'writing',
      note: '검수 완료',
    });
    expect(repository.markFailed).not.toHaveBeenCalled();
  });

  it('includes examId in the completed metadata when the event carried one', async () => {
    const generated = buildGeneratedSet();
    const questionGenerator = {
      generate: jest.fn().mockResolvedValue(generated),
    } as unknown as QuestionGeneratorPort;
    const questionService = {
      bulkCreateDrafts: jest.fn().mockResolvedValue([]),
    } as unknown as QuestionService;
    const repository = buildRepository();
    const listener = new DocumentUploadedListener(repository, questionGenerator, questionService);
    const event = new DocumentUploadedEvent('1', 'documents/x.pdf', 'x.pdf', '5');

    await listener.handle(event);

    expect(repository.markCompleted).toHaveBeenCalledWith(
      '1',
      expect.objectContaining({ examId: '5' }),
    );
  });

  it('marks FAILED with the error message when generation throws', async () => {
    const questionGenerator = {
      generate: jest.fn().mockRejectedValue(new Error('AI 서비스 다운')),
    } as unknown as QuestionGeneratorPort;
    const questionService = { bulkCreateDrafts: jest.fn() } as unknown as QuestionService;
    const repository = buildRepository();
    const listener = new DocumentUploadedListener(repository, questionGenerator, questionService);
    const event = new DocumentUploadedEvent('1', 'documents/x.pdf', 'x.pdf');

    await listener.handle(event);

    expect(repository.markFailed).toHaveBeenCalledWith('1', 'AI 서비스 다운');
    expect(repository.markCompleted).not.toHaveBeenCalled();
  });

  it('marks FAILED with a generic message when bulkCreateDrafts throws a non-Error value', async () => {
    const generated = buildGeneratedSet();
    const questionGenerator = {
      generate: jest.fn().mockResolvedValue(generated),
    } as unknown as QuestionGeneratorPort;
    const questionService = {
      bulkCreateDrafts: jest.fn().mockRejectedValue('db down'),
    } as unknown as QuestionService;
    const repository = buildRepository();
    const listener = new DocumentUploadedListener(repository, questionGenerator, questionService);
    const event = new DocumentUploadedEvent('1', 'documents/x.pdf', 'x.pdf');

    await listener.handle(event);

    expect(repository.markFailed).toHaveBeenCalledWith('1', '문항 생성에 실패했습니다.');
  });
});
