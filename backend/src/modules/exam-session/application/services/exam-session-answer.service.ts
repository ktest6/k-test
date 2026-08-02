import { Injectable } from '@nestjs/common';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { AnswerService } from '../../../answer/application/services/answer.service';
import { Answer } from '../../../answer/domain/entities/answer.entity';
import { AnswerType } from '../../../answer/domain/enums/answer-type.enum';
import { ScoringService } from '../../../scoring/application/services/scoring.service';
import { ExamSessionQuestionService } from './exam-session-question.service';
import { ExamSessionService } from './exam-session.service';

export interface SaveAnswerInput {
  type: AnswerType;
  contentText?: string;
  audioFileUrl?: string;
}

export interface AnswerWithScoreResult {
  answer: Answer;
  graded: boolean;
  score: Record<string, unknown> | null;
}

@Injectable()
export class ExamSessionAnswerService {
  constructor(
    private readonly examSessionService: ExamSessionService,
    private readonly examSessionQuestionService: ExamSessionQuestionService,
    private readonly answerService: AnswerService,
    private readonly scoringService: ScoringService,
  ) {}

  async save(
    examSessionId: string,
    questionId: string,
    userId: string,
    input: SaveAnswerInput,
  ): Promise<AnswerWithScoreResult> {
    await this.examSessionService.assertActiveSession(examSessionId, userId);
    await this.examSessionQuestionService.getQuestion(examSessionId, questionId, userId);

    const answer = await this.answerService.save({
      examSessionId,
      questionId,
      type: input.type,
      contentText: input.contentText ?? null,
      audioFileUrl: input.audioFileUrl ?? null,
    });

    return this.withScore(answer);
  }

  async get(
    examSessionId: string,
    questionId: string,
    userId: string,
  ): Promise<AnswerWithScoreResult> {
    // 세션이 끝난 뒤에도(제출/만료) 자기 답안은 읽을 수 있어야 하므로 소유권/문항 소속만 확인한다.
    await this.examSessionQuestionService.getQuestion(examSessionId, questionId, userId);

    const answer = await this.answerService.findBySessionAndQuestion(examSessionId, questionId);
    if (!answer) {
      throw new NotFoundDomainException('아직 저장된 답안이 없습니다.');
    }

    return this.withScore(answer);
  }

  private async withScore(answer: Answer): Promise<AnswerWithScoreResult> {
    const score = await this.scoringService.findByAnswerId(answer.id);
    return { answer, graded: score !== null, score: score?.rawResponse ?? null };
  }
}
