import { AnswerType } from '../../../answer/domain/enums/answer-type.enum';
import { AnswerSavedEvent } from '../../../answer/domain/events/answer-saved.event';
import { ScoringProviderPort } from '../../../ai/domain/ports/scoring-provider.port';
import { Question } from '../../../question/domain/entities/question.entity';
import { QuestionSectionType } from '../../../question/domain/enums/question-section-type.enum';
import { QuestionService } from '../../../question/application/services/question.service';
import { ScoringService } from '../services/scoring.service';
import { AnswerSavedListener } from './answer-saved.listener';

function buildQuestion(): Question {
  return new Question(
    '50',
    QuestionSectionType.SITUATION_DESCRIPTION,
    {
      preparationSeconds: 40,
      responseSeconds: 60,
      guideTexts: ['안내문구'],
      instruction: '그림을 보고 상황을 설명하세요.',
    },
    null,
    [
      {
        id: '1',
        code: 'c1',
        description: '상황을 정확히 묘사했는가',
        weight: 1.5,
        displayOrder: 0,
      },
    ],
    new Date(),
  );
}

describe('AnswerSavedListener.handle', () => {
  it('builds the score request from the question and records the result', async () => {
    const question = buildQuestion();
    const findById = jest.fn().mockResolvedValue(question);
    const questionService = { findById } as unknown as QuestionService;
    const record = jest.fn().mockResolvedValue(undefined);
    const scoringService = { record } as unknown as ScoringService;
    const rawResponse = { total_score: 80 };
    const score = jest.fn().mockResolvedValue(rawResponse);
    const scoringProvider = { score } as unknown as ScoringProviderPort;
    const listener = new AnswerSavedListener(questionService, scoringService, scoringProvider);
    const event = new AnswerSavedEvent(
      '500',
      '50',
      AnswerType.AUDIO,
      null,
      '12/100/50.webm',
      11760,
    );

    await listener.handle(event);

    expect(findById).toHaveBeenCalledWith('50');
    expect(score).toHaveBeenCalledWith({
      answerId: '500',
      answerType: 'AUDIO',
      contentText: null,
      audioFileUrl: '12/100/50.webm',
      durationMs: 11760,
      item: {
        itemId: '50',
        prompt: '그림을 보고 상황을 설명하세요.',
        expectedRegister: 'any',
        checklist: [{ id: 'c1', description: '상황을 정확히 묘사했는가', weight: 1.5 }],
      },
    });
    expect(record).toHaveBeenCalledWith({ answerId: '500', rawResponse });
  });

  it('swallows errors from the scoring provider without throwing', async () => {
    const questionService = {
      findById: jest.fn().mockResolvedValue(buildQuestion()),
    } as unknown as QuestionService;
    const record = jest.fn();
    const scoringService = { record } as unknown as ScoringService;
    const scoringProvider = {
      score: jest.fn().mockRejectedValue(new Error('assessment unreachable')),
    } as unknown as ScoringProviderPort;
    const listener = new AnswerSavedListener(questionService, scoringService, scoringProvider);
    const event = new AnswerSavedEvent('500', '50', AnswerType.TEXT, '내용', null, null);

    await expect(listener.handle(event)).resolves.toBeUndefined();
    expect(record).not.toHaveBeenCalled();
  });

  it('swallows errors when the question no longer exists', async () => {
    const questionService = {
      findById: jest.fn().mockRejectedValue(new Error('문항을 찾을 수 없습니다.')),
    } as unknown as QuestionService;
    const scoringService = { record: jest.fn() } as unknown as ScoringService;
    const scoringProvider = { score: jest.fn() } as unknown as ScoringProviderPort;
    const listener = new AnswerSavedListener(questionService, scoringService, scoringProvider);
    const event = new AnswerSavedEvent('500', '50', AnswerType.TEXT, '내용', null, null);

    await expect(listener.handle(event)).resolves.toBeUndefined();
  });
});
