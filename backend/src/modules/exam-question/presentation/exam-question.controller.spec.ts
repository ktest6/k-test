import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { Role } from '../../../common/enums/role.enum';
import { Question } from '../../question/domain/entities/question.entity';
import { QuestionSectionType } from '../../question/domain/enums/question-section-type.enum';
import { ExamQuestion } from '../domain/entities/exam-question.entity';
import { ExamQuestionService } from '../application/services/exam-question.service';
import { ExamQuestionController } from './exam-question.controller';

function buildAdmin(): AuthenticatedUser {
  return { id: '5', email: 'admin@test.com', role: Role.ADMIN };
}

function buildAssignment(): ExamQuestion {
  return new ExamQuestion('1', '1', '2', '5', new Date('2026-06-01T00:00:00.000Z'));
}

function buildQuestion(): Question {
  return new Question(
    '2',
    QuestionSectionType.SITUATION_DESCRIPTION,
    { preparationSeconds: 40, responseSeconds: 60, guideTexts: ['안내문구'], instruction: 'p' },
    null,
    [{ id: '1', code: 'c1', description: '설명', weight: 1.5, displayOrder: 0 }],
    new Date(),
  );
}

describe('ExamQuestionController.assign', () => {
  it('delegates to ExamQuestionService.assign with the caller as assignedBy, and maps the response', async () => {
    const assignment = buildAssignment();
    const assign = jest.fn().mockResolvedValue(assignment);
    const controller = new ExamQuestionController({ assign } as unknown as ExamQuestionService);

    const result = await controller.assign('1', { questionId: '2' }, buildAdmin());

    expect(assign).toHaveBeenCalledWith('1', '2', '5');
    expect(result).toEqual({
      id: '1',
      examId: '1',
      questionId: '2',
      createdAt: assignment.createdAt,
    });
  });
});

describe('ExamQuestionController.unassign', () => {
  it('delegates to ExamQuestionService.unassign and returns the identifying pair', async () => {
    const unassign = jest.fn().mockResolvedValue(undefined);
    const controller = new ExamQuestionController({ unassign } as unknown as ExamQuestionService);

    const result = await controller.unassign('1', '2');

    expect(unassign).toHaveBeenCalledWith('1', '2');
    expect(result).toEqual({ examId: '1', questionId: '2' });
  });
});

describe('ExamQuestionController.list', () => {
  it('delegates to ExamQuestionService.listAssignedQuestions and maps checklist items', async () => {
    const listAssignedQuestions = jest.fn().mockResolvedValue([buildQuestion()]);
    const controller = new ExamQuestionController({
      listAssignedQuestions,
    } as unknown as ExamQuestionService);

    const result = await controller.list('1');

    expect(listAssignedQuestions).toHaveBeenCalledWith('1');
    expect(result).toEqual([
      {
        id: '2',
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
