import { createHash } from 'node:crypto';
import { Inject, Injectable } from '@nestjs/common';
import {
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { ExamQuestionService } from '../../../exam-question/application/services/exam-question.service';
import { Question } from '../../../question/domain/entities/question.entity';
import {
  EXAM_SESSION_REPOSITORY,
  ExamSessionRepository,
} from '../../domain/exam-session.repository.interface';

/** examSessionId를 시드로 한 결정적 셔플 — 같은 세션에서는 항상 같은 순서가 나오지만(새로고침해도 안 바뀜), 세션마다 순서가 다르다. */
function shuffleKey(examSessionId: string, questionId: string): string {
  return createHash('sha256').update(`${examSessionId}:${questionId}`).digest('hex');
}

@Injectable()
export class ExamSessionQuestionService {
  constructor(
    @Inject(EXAM_SESSION_REPOSITORY) private readonly examSessionRepository: ExamSessionRepository,
    private readonly examQuestionService: ExamQuestionService,
  ) {}

  async listQuestions(examSessionId: string, userId: string): Promise<Question[]> {
    const examId = await this.getOwnedSessionExamId(examSessionId, userId);
    const questions = await this.examQuestionService.listAssignedQuestions(examId);

    return [...questions].sort((a, b) =>
      shuffleKey(examSessionId, a.id) < shuffleKey(examSessionId, b.id) ? -1 : 1,
    );
  }

  async getQuestion(examSessionId: string, questionId: string, userId: string): Promise<Question> {
    const examId = await this.getOwnedSessionExamId(examSessionId, userId);
    const questions = await this.examQuestionService.listAssignedQuestions(examId);

    const question = questions.find((q) => q.id === questionId);
    if (!question) {
      throw new NotFoundDomainException(`문항(${questionId})을 찾을 수 없습니다.`);
    }
    return question;
  }

  private async getOwnedSessionExamId(examSessionId: string, userId: string): Promise<string> {
    const session = await this.examSessionRepository.findById(examSessionId);
    if (!session) {
      throw new NotFoundDomainException(`응시 세션(${examSessionId})을 찾을 수 없습니다.`);
    }
    if (session.userId !== userId) {
      throw new ForbiddenDomainException('세션 소유자가 아닙니다.');
    }
    return session.examId;
  }
}
