import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { Document } from '../domain/entities/document.entity';
import { DocumentStatus } from '../domain/enums/document-status.enum';
import { DocumentService } from '../application/services/document.service';
import { QuestionService } from '../../question/application/services/question.service';
import { Question } from '../../question/domain/entities/question.entity';
import { QuestionSectionType } from '../../question/domain/enums/question-section-type.enum';
import { DocumentController } from './document.controller';

function buildAdmin(): AuthenticatedUser {
  return { id: '1', email: 'admin@test.com', role: Role.ADMIN };
}

function buildDocument(
  overrides: Partial<{ status: DocumentStatus; errorMessage: string | null }> = {},
): Document {
  return new Document(
    '1',
    'documents/x.pdf',
    'x.pdf',
    '1',
    overrides.status ?? DocumentStatus.UPLOADED,
    null,
    overrides.errorMessage ?? null,
    new Date(),
  );
}

function buildQuestion(): Question {
  return new Question(
    '1',
    QuestionSectionType.SITUATION_DESCRIPTION,
    { preparationSeconds: 40, responseSeconds: 60, guideTexts: ['안내문구'], instruction: 'p' },
    '1',
    [{ id: '1', code: 'c1', description: '설명', weight: 1.5, displayOrder: 0 }],
    new Date(),
  );
}

describe('DocumentController.upload', () => {
  it('delegates to DocumentService.upload and maps the response', async () => {
    const document = buildDocument();
    const upload = jest.fn().mockResolvedValue(document);
    const documentService = { upload } as unknown as DocumentService;
    const controller = new DocumentController(documentService, {} as unknown as QuestionService);

    const result = await controller.upload(buildAdmin(), { filePath: 'documents/x.pdf' });

    expect(upload).toHaveBeenCalledWith('1', { filePath: 'documents/x.pdf' });
    expect(result).toEqual({ id: '1', status: DocumentStatus.UPLOADED });
  });
});

describe('DocumentController.findById', () => {
  it('delegates to DocumentService.findById and maps the response', async () => {
    const document = buildDocument({ status: DocumentStatus.FAILED, errorMessage: '실패' });
    const findById = jest.fn().mockResolvedValue(document);
    const documentService = { findById } as unknown as DocumentService;
    const controller = new DocumentController(documentService, {} as unknown as QuestionService);

    const result = await controller.findById('1');

    expect(findById).toHaveBeenCalledWith('1');
    expect(result).toEqual({
      id: '1',
      filePath: 'documents/x.pdf',
      fileName: 'x.pdf',
      status: DocumentStatus.FAILED,
      errorMessage: '실패',
      createdAt: document.createdAt,
    });
  });
});

describe('DocumentController.getQuestions', () => {
  it('checks the document exists, then maps questions with their checklist items', async () => {
    const findById = jest.fn().mockResolvedValue(buildDocument());
    const documentService = { findById } as unknown as DocumentService;
    const findByDocumentId = jest.fn().mockResolvedValue([buildQuestion()]);
    const questionService = { findByDocumentId } as unknown as QuestionService;
    const controller = new DocumentController(documentService, questionService);

    const result = await controller.getQuestions('1');

    expect(findById).toHaveBeenCalledWith('1');
    expect(findByDocumentId).toHaveBeenCalledWith('1');
    expect(result).toEqual([
      {
        id: '1',
        part: QuestionSectionType.SITUATION_DESCRIPTION,
        content: {
          preparationSeconds: 40,
          responseSeconds: 60,
          guideTexts: ['안내문구'],
          instruction: 'p',
        },
        checklistItems: [{ id: '1', code: 'c1', description: '설명', weight: 1.5 }],
      },
    ]);
  });
});
