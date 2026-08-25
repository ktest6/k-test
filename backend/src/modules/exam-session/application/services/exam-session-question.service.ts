import { createHash } from 'node:crypto';
import { Inject, Injectable } from '@nestjs/common';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { notFound } from '../../../../common/exceptions/error-messages';
import { AnswerService } from '../../../answer/application/services/answer.service';
import { QuestionService } from '../../../question/application/services/question.service';
import { Question } from '../../../question/domain/entities/question.entity';
import { QuestionSectionType } from '../../../question/domain/enums/question-section-type.enum';
import {
  SKIPPED_QUESTION_REPOSITORY,
  SkippedQuestionRepository,
} from '../../domain/skipped-question.repository.interface';
import { ExamSessionService } from './exam-session.service';

/** 섹션 노출 순서 — 1. 상황 묘사하기 → 2. 읽고 설명하기 → 3. 질문에 대답하기. */
const SECTION_ORDER: QuestionSectionType[] = [
  QuestionSectionType.SITUATION_DESCRIPTION,
  QuestionSectionType.READ_AND_EXPLAIN,
  QuestionSectionType.ANSWER_QUESTION,
];

/** 회차(Exam) 개념이 없어져서, 파트마다 이 개수만큼 문항 풀에서 뽑아 세션에 배정한다. */
const QUESTIONS_PER_PART = 2;

/** examSessionId를 시드로 한 결정적 해시 — 선택("이 세션엔 어떤 문항")과 정렬(같은 섹션 안 순서) 둘 다 이걸로 한다. 같은 세션은 새로고침해도 항상 같은 결과, 세션마다는 다른 결과. */
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
    private readonly examSessionService: ExamSessionService,
    @Inject(SKIPPED_QUESTION_REPOSITORY)
    private readonly skippedQuestionRepository: SkippedQuestionRepository,
    private readonly questionService: QuestionService,
    private readonly answerService: AnswerService,
  ) {}

  /**
   * 세션에 배정된 문항 6개(파트별 2개, 문항 풀에서 세션별 결정적 랜덤으로 선택) —
   * 섹션 순서(SECTION_ORDER) 그대로 묶여서 나온다. 회차(Exam)가 없어졌으므로
   * "이 세션엔 어떤 문항인가" 자체가 examSessionId 하나로 매번 재현 가능하게
   * 계산된다 — 별도로 저장하지 않는다.
   */
  async getAssignedQuestions(examSessionId: string): Promise<Question[]> {
    const byPart = await Promise.all(
      SECTION_ORDER.map((part) => this.questionService.findByPart(part)),
    );

    return SECTION_ORDER.flatMap((_part, index) => {
      const pool = byPart[index];
      return [...pool]
        .sort((a, b) =>
          shuffleKey(examSessionId, a.id) < shuffleKey(examSessionId, b.id) ? -1 : 1,
        )
        .slice(0, QUESTIONS_PER_PART);
    });
  }

  /** 본인인증/이어폰 확인이 다 끝나야 문항에 접근할 수 있다. */
  async listQuestions(examSessionId: string, userId: string): Promise<SessionQuestion[]> {
    await this.examSessionService.assertVerifiedSession(examSessionId, userId);

    const [questions, answeredIds, skippedIds] = await Promise.all([
      this.getAssignedQuestions(examSessionId),
      this.answerService.listAnsweredQuestionIds(examSessionId),
      this.skippedQuestionRepository.listSkippedQuestionIds(examSessionId),
    ]);
    const answered = new Set(answeredIds);
    const skipped = new Set(skippedIds);

    return questions.map((question) => ({
      question,
      answered: answered.has(question.id),
      skipped: skipped.has(question.id),
    }));
  }

  /** isAdmin이면 세션 소유자가 아니어도, 검증이 안 끝났어도 조회를 허용한다(관리자는 항상 조회 가능). */
  async getQuestion(
    examSessionId: string,
    questionId: string,
    userId: string,
    isAdmin = false,
  ): Promise<SessionQuestion> {
    if (isAdmin) {
      await this.examSessionService.getSessionOrThrow(examSessionId);
    } else {
      await this.examSessionService.assertVerifiedSession(examSessionId, userId);
    }

    const questions = await this.getAssignedQuestions(examSessionId);
    const question = questions.find((q) => q.id === questionId);
    if (!question) {
      throw new NotFoundDomainException(notFound('Question', questionId));
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
}
