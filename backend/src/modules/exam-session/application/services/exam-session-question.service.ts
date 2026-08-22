import { createHash } from 'node:crypto';
import { Inject, Injectable } from '@nestjs/common';
import {
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { AnswerService } from '../../../answer/application/services/answer.service';
import { ExamQuestionService } from '../../../exam-question/application/services/exam-question.service';
import { Question } from '../../../question/domain/entities/question.entity';
import { QuestionSectionType } from '../../../question/domain/enums/question-section-type.enum';
import {
  EXAM_SESSION_REPOSITORY,
  ExamSessionRepository,
} from '../../domain/exam-session.repository.interface';
import {
  SKIPPED_QUESTION_REPOSITORY,
  SkippedQuestionRepository,
} from '../../domain/skipped-question.repository.interface';

/** 섹션 노출 순서 — 1. 상황 묘사하기 → 2. 읽고 설명하기 → 3. 질문에 대답하기. */
const SECTION_ORDER: QuestionSectionType[] = [
  QuestionSectionType.SITUATION_DESCRIPTION,
  QuestionSectionType.READ_AND_EXPLAIN,
  QuestionSectionType.ANSWER_QUESTION,
];

/** examSessionId를 시드로 한 결정적 셔플 — 같은 세션에서는 항상 같은 순서가 나오지만(새로고침해도 안 바뀜), 세션마다 순서가 다르다. */
function shuffleKey(examSessionId: string, questionId: string): string {
  return createHash('sha256').update(`${examSessionId}:${questionId}`).digest('hex');
}

/** 문항 내용 + 이 세션에서 이미 답했는지/건너뛰었는지 여부. 프런트가 이 플래그로 다음에 풀 문항을 직접 계산한다. */
export interface SessionQuestion {
  question: Question;
  answered: boolean;
  skipped: boolean;
}

@Injectable()
export class ExamSessionQuestionService {
  constructor(
    @Inject(EXAM_SESSION_REPOSITORY) private readonly examSessionRepository: ExamSessionRepository,
    @Inject(SKIPPED_QUESTION_REPOSITORY)
    private readonly skippedQuestionRepository: SkippedQuestionRepository,
    private readonly examQuestionService: ExamQuestionService,
    private readonly answerService: AnswerService,
  ) {}

  /** 섹션 순서(SECTION_ORDER)로 먼저 묶고, 같은 섹션 안에서는 세션별 결정적 셔플로 섞는다. */
  async listQuestions(examSessionId: string, userId: string): Promise<SessionQuestion[]> {
    const examId = await this.getSessionExamId(examSessionId, userId, false);
    const [questions, answeredIds, skippedIds] = await Promise.all([
      this.examQuestionService.listAssignedQuestions(examId),
      this.answerService.listAnsweredQuestionIds(examSessionId),
      this.skippedQuestionRepository.listSkippedQuestionIds(examSessionId),
    ]);
    const answered = new Set(answeredIds);
    const skipped = new Set(skippedIds);

    const sorted = [...questions].sort((a, b) => {
      const sectionDiff = SECTION_ORDER.indexOf(a.part) - SECTION_ORDER.indexOf(b.part);
      if (sectionDiff !== 0) {
        return sectionDiff;
      }
      return shuffleKey(examSessionId, a.id) < shuffleKey(examSessionId, b.id) ? -1 : 1;
    });

    return sorted.map((question) => ({
      question,
      answered: answered.has(question.id),
      skipped: skipped.has(question.id),
    }));
  }

  /** isAdmin이면 세션 소유자가 아니어도 조회를 허용한다(관리자는 항상 조회 가능). */
  async getQuestion(
    examSessionId: string,
    questionId: string,
    userId: string,
    isAdmin = false,
  ): Promise<SessionQuestion> {
    const examId = await this.getSessionExamId(examSessionId, userId, isAdmin);
    const questions = await this.examQuestionService.listAssignedQuestions(examId);

    const question = questions.find((q) => q.id === questionId);
    if (!question) {
      throw new NotFoundDomainException(`문항(${questionId})을 찾을 수 없습니다.`);
    }

    const [answeredIds, skippedIds] = await Promise.all([
      this.answerService.listAnsweredQuestionIds(examSessionId),
      this.skippedQuestionRepository.listSkippedQuestionIds(examSessionId),
    ]);
    return {
      question,
      answered: answeredIds.includes(questionId),
      skipped: skippedIds.includes(questionId),
    };
  }

  private async getSessionExamId(
    examSessionId: string,
    userId: string,
    isAdmin: boolean,
  ): Promise<string> {
    const session = await this.examSessionRepository.findById(examSessionId);
    if (!session) {
      throw new NotFoundDomainException(`응시 세션(${examSessionId})을 찾을 수 없습니다.`);
    }
    if (!isAdmin && session.userId !== userId) {
      throw new ForbiddenDomainException('세션 소유자가 아닙니다.');
    }
    return session.examId;
  }
}
