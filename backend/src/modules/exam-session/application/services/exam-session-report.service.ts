import { Inject, Injectable, Logger } from '@nestjs/common';
import { describeError } from '../../../../common/utils/describe-error.util';
import { AnswerService } from '../../../answer/application/services/answer.service';
import { Answer } from '../../../answer/domain/entities/answer.entity';
import { AnswerType } from '../../../answer/domain/enums/answer-type.enum';
import {
  FINALIZE_PROVIDER,
  FinalizeProviderPort,
} from '../../../ai/domain/ports/finalize-provider.port';
import {
  SCORING_PROVIDER,
  ScoringProviderPort,
} from '../../../ai/domain/ports/scoring-provider.port';
import { ExamQuestionService } from '../../../exam-question/application/services/exam-question.service';
import { QuestionService } from '../../../question/application/services/question.service';
import { ExamResultService } from '../../../scoring/application/services/exam-result.service';
import { ScoringService } from '../../../scoring/application/services/scoring.service';
import {
  EXAM_SESSION_REPOSITORY,
  ExamSessionRepository,
} from '../../domain/exam-session.repository.interface';
import {
  SKIPPED_QUESTION_REPOSITORY,
  SkippedQuestionRepository,
} from '../../domain/skipped-question.repository.interface';

/**
 * "문항이 하나 처리(답했거나 건너뛰었거나)될 때마다" 세션이 다 끝났는지 확인하고,
 * 다 끝났으면 그 자리에서 최종 리포트(/finalize)를 제출한다. `ExamSessionAnswerService`의
 * save()/skip() 끝에서 매번 호출된다 — 트리거가 명시적인 별도 API가 아니라
 * "마지막 문항이 방금 처리됐다"는 사실 그 자체다.
 */
@Injectable()
export class ExamSessionReportService {
  private readonly logger = new Logger(ExamSessionReportService.name);

  constructor(
    @Inject(EXAM_SESSION_REPOSITORY) private readonly examSessionRepository: ExamSessionRepository,
    @Inject(SKIPPED_QUESTION_REPOSITORY)
    private readonly skippedQuestionRepository: SkippedQuestionRepository,
    private readonly examQuestionService: ExamQuestionService,
    private readonly questionService: QuestionService,
    private readonly answerService: AnswerService,
    private readonly scoringService: ScoringService,
    private readonly examResultService: ExamResultService,
    @Inject(SCORING_PROVIDER) private readonly scoringProvider: ScoringProviderPort,
    @Inject(FINALIZE_PROVIDER) private readonly finalizeProvider: FinalizeProviderPort,
  ) {}

  /**
   * 배정 문항 수 == (답변 + 건너뜀) 합이 아니면 아직 끝난 게 아니라 그냥 반환한다.
   * 다 끝났으면 세션은 무조건 SUBMITTED로 넘긴다 — /finalize 호출이 실패해도
   * (assessment 장애 등) 마찬가지다. 응시자는 이미 배정된 문항을 전부 처리했으므로
   * 세션 상태(SessionStatus)는 "응시가 끝났는가"만 반영해야 하고, AI 서비스
   * 장애 때문에 INPROGRESS로 방치하면 재접속 시 재개(resume) 로직을 타서
   * resumeCount가 올라가다 BLOCKED까지 걸릴 수 있다 — 이미 끝난 사람인데도.
   * finalize 성공 여부는 tb_exam_results에 결과가 있는지로 따로 판정한다
   * (`syncPendingReports`가 그 기준으로 재시도 대상을 찾는다).
   */
  async checkAndFinalize(examSessionId: string, userId: string): Promise<void> {
    const session = await this.examSessionRepository.findById(examSessionId);
    if (!session) {
      return;
    }

    const [assignedQuestions, answeredIds, skippedIds] = await Promise.all([
      this.examQuestionService.listAssignedQuestions(session.examId),
      this.answerService.listAnsweredQuestionIds(examSessionId),
      this.skippedQuestionRepository.listSkippedQuestionIds(examSessionId),
    ]);

    const handledIds = new Set([...answeredIds, ...skippedIds]);
    const isComplete = assignedQuestions.every((question) => handledIds.has(question.id));
    if (!isComplete) {
      return;
    }

    try {
      const items = await this.buildScoredItems(examSessionId);
      const expectedItems = assignedQuestions.map((question) => ({
        itemId: question.id,
        mode: 'speaking' as const, // 이 시험 흐름의 답안은 전부 음성(AnswerType.AUDIO)이다.
      }));

      const finalizeResponse = await this.finalizeProvider.finalize({
        sessionId: examSessionId,
        candidateId: userId,
        items,
        expectedItems,
      });

      await this.examResultService.record(
        {
          examSessionId,
          finalGrade:
            typeof finalizeResponse.overall_grade === 'string'
              ? finalizeResponse.overall_grade
              : '',
          percentile:
            typeof finalizeResponse.percentile === 'number' ? finalizeResponse.percentile : null,
          domainScores: (finalizeResponse.subscores as Record<string, unknown>[] | undefined)
            ? { subscores: finalizeResponse.subscores }
            : null,
          crossValidationSignals:
            (finalizeResponse.cross_mode_check as Record<string, unknown> | undefined) ?? null,
          rawResponse: finalizeResponse,
        },
        userId,
      );
    } catch (err) {
      // tb_exam_results에 아직 없으므로 syncPendingReports가 나중에 다시 시도한다.
      this.logger.error(
        `최종 리포트 제출 실패, 나중에 재시도됨 (examSessionId=${examSessionId}): ${describeError(err)}`,
      );
    }

    await this.examSessionRepository.markSubmitted(examSessionId);
  }

  /**
   * SUBMITTED인데 아직 tb_exam_results가 없는 세션(= finalize가 실패해서 리포트가
   * 안 남은 경우)을 훑어서 하나씩 checkAndFinalize를 다시 시도한다.
   * `ExamSessionReportRetryScheduler`가 주기적으로 호출 — 응시자는 더 이상 답안/
   * 스킵을 보내지 않으므로 checkAndFinalize가 다시 불릴 자연스러운 계기가 없다.
   * 세션 하나가 실패해도 나머지는 계속 처리한다. 반환값은 이번 호출에서 실제로
   * 리포트 제출까지 완료한 세션 수(로깅용).
   */
  async syncPendingReports(): Promise<number> {
    const [submittedSessions, sessionIdsWithResult] = await Promise.all([
      this.examSessionRepository.findAllSubmitted(),
      this.examResultService.listExamSessionIdsWithResult(),
    ]);
    const withResult = new Set(sessionIdsWithResult);
    const pending = submittedSessions.filter((session) => !withResult.has(session.id));

    const results = await Promise.all(
      pending.map(async (session) => {
        try {
          await this.checkAndFinalize(session.id, session.userId);
          const result = await this.examResultService.findByExamSessionId(session.id);
          return result !== null;
        } catch (err) {
          this.logger.error(
            `최종 리포트 재시도 실패 (examSessionId=${session.id}): ${describeError(err)}`,
          );
          return false;
        }
      }),
    );

    return results.filter(Boolean).length;
  }

  /**
   * 답변한 문항 중 아직 채점(tb_score) 결과가 없는 게 있으면 이 자리에서 동기적으로
   * 채점을 마저 완료시킨다. 답안 저장 시 이벤트로 비동기 채점되는 경로와 별개로,
   * finalize 직전엔 "채점이 다 끝난 상태"가 보장돼야 하기 때문이다(마지막 문항일수록
   * 비동기 채점이 아직 안 끝났을 가능성이 높다).
   */
  private async buildScoredItems(examSessionId: string): Promise<Record<string, unknown>[]> {
    const answers = await this.answerService.listBySession(examSessionId);

    return Promise.all(
      answers.map(async (answer) => {
        const existing = await this.scoringService.findByAnswerId(answer.id);
        if (existing) {
          return existing.rawResponse;
        }
        return this.scoreNow(answer);
      }),
    );
  }

  private async scoreNow(answer: Answer): Promise<Record<string, unknown>> {
    const question = await this.questionService.findById(answer.questionId);

    const rawResponse = await this.scoringProvider.score({
      answerId: answer.id,
      answerType: answer.type === AnswerType.AUDIO ? 'AUDIO' : 'TEXT',
      contentText: answer.contentText,
      audioFileUrl: answer.audioFileUrl,
      durationMs: null,
      item: {
        itemId: question.id,
        prompt: question.content.instruction ?? question.content.guideTexts?.join(' ') ?? '',
        // assessment는 'formal'|'polite'|'any'만 허용한다(빈 문자열이면 422) — 문항별
        // 기대 격식은 아직 모델링돼 있지 않아 가장 중립적인 'any'로 채운다.
        expectedRegister: 'any',
        checklist: question.checklistItems.map((item) => ({
          id: item.code,
          description: item.description,
          weight: item.weight,
        })),
      },
    });

    try {
      await this.scoringService.record({ answerId: answer.id, rawResponse });
    } catch (err) {
      // 저장이 실패해도(레이스로 이미 이벤트 리스너가 저장한 직후 등) 방금 받은
      // 채점 결과 자체는 finalize에 그대로 실어보낼 수 있으니 흐름을 막지 않는다.
      this.logger.warn(`채점 결과 저장 실패 (answerId=${answer.id}): ${describeError(err)}`);
    }

    return rawResponse;
  }
}
