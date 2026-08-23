import { Inject, Injectable } from '@nestjs/common';
import {
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { AnswerService } from '../../../answer/application/services/answer.service';
import { QuestionSectionType } from '../../../question/domain/enums/question-section-type.enum';
import {
  PROCTORING_EVENT_REPOSITORY,
  ProctoringEventRepository,
} from '../../../monitoring/domain/proctoring-event.repository.interface';
import { ProctoringSeverity } from '../../../monitoring/domain/entities/proctoring-event.entity';
import { ExamResultService } from '../../../scoring/application/services/exam-result.service';
import { ScoringService } from '../../../scoring/application/services/scoring.service';
import { UserService } from '../../../user/application/services/user.service';
import {
  EXAM_SESSION_REPOSITORY,
  ExamSessionRepository,
} from '../../domain/exam-session.repository.interface';
import {
  SKIPPED_QUESTION_REPOSITORY,
  SkippedQuestionRepository,
} from '../../domain/skipped-question.repository.interface';
import { ExamSessionQuestionService } from './exam-session-question.service';

export interface ReportTask {
  questionId: string;
  part: QuestionSectionType;
  skipped: boolean;
  response: string | null;
  requiredPoints: { description: string; met: boolean }[] | null;
}

export interface ReportDomainScore {
  area: string;
  score: number;
}

export interface ReportViolation {
  eventType: string;
  severity: ProctoringSeverity;
  count: number;
}

export interface Report {
  examResultId: string;
  examSessionId: string;
  candidateName: string;
  startedAt: Date;
  finalGrade: string;
  percentile: number | null;
  domainScores: ReportDomainScore[];
  tasks: ReportTask[];
  violations: ReportViolation[];
}

/**
 * 마이페이지 "리포트 보기" — 최종 등급/영역별 점수/문항별 답변·체크리스트·부정행위
 * 로그를 한 번에 모아서 준다. tb_exam_results.raw_response는 채점 원본 전체(문항별
 * 세부 근거 포함)가 아니라 finalize 응답만 담고 있어서, 문항별 답변/체크리스트는
 * tb_score(답변별 채점 결과)에서 따로 모은다.
 */
@Injectable()
export class MypageReportService {
  constructor(
    @Inject(EXAM_SESSION_REPOSITORY) private readonly examSessionRepository: ExamSessionRepository,
    @Inject(SKIPPED_QUESTION_REPOSITORY)
    private readonly skippedQuestionRepository: SkippedQuestionRepository,
    @Inject(PROCTORING_EVENT_REPOSITORY)
    private readonly proctoringEventRepository: ProctoringEventRepository,
    private readonly examSessionQuestionService: ExamSessionQuestionService,
    private readonly answerService: AnswerService,
    private readonly scoringService: ScoringService,
    private readonly examResultService: ExamResultService,
    private readonly userService: UserService,
  ) {}

  async getReport(examResultId: string, userId: string): Promise<Report> {
    const examResult = await this.examResultService.findById(examResultId);
    if (!examResult) {
      throw new NotFoundDomainException(`리포트(${examResultId})를 찾을 수 없습니다.`);
    }

    const session = await this.examSessionRepository.findById(examResult.examSessionId);
    if (!session) {
      throw new NotFoundDomainException(
        `응시 세션(${examResult.examSessionId})을 찾을 수 없습니다.`,
      );
    }
    if (session.userId !== userId) {
      throw new ForbiddenDomainException('본인의 리포트가 아닙니다.');
    }

    const [user, assignedQuestions, answers, skippedIds, events] = await Promise.all([
      this.userService.findById(userId),
      this.examSessionQuestionService.getAssignedQuestions(session.id),
      this.answerService.listBySession(session.id),
      this.skippedQuestionRepository.listSkippedQuestionIds(session.id),
      this.proctoringEventRepository.findByExamSessionId(session.id),
    ]);

    const answerByQuestionId = new Map(answers.map((answer) => [answer.questionId, answer]));
    const skippedQuestionIds = new Set(skippedIds);

    const tasks = await Promise.all(
      assignedQuestions.map(async (question): Promise<ReportTask> => {
        const answer = answerByQuestionId.get(question.id);
        if (!answer) {
          // 스킵했거나(명시적) 방치 세션 강제 제출로 아예 손도 안 댄 경우 — 리포트
          // 화면에서는 둘 다 "건너뛴 문항"으로 같이 보여준다.
          return {
            questionId: question.id,
            part: question.part,
            skipped: true,
            response: null,
            requiredPoints: null,
          };
        }

        const score = await this.scoringService.findByAnswerId(answer.id);
        const meta = score?.rawResponse.meta as Record<string, unknown> | undefined;
        const response =
          typeof meta?.stt_transcript === 'string' ? meta.stt_transcript : answer.contentText;
        const checklistResults = score?.rawResponse.checklist_results as
          { description?: unknown; met?: unknown }[] | undefined;
        const requiredPoints = Array.isArray(checklistResults)
          ? checklistResults.map((item) => ({
              description: typeof item.description === 'string' ? item.description : '',
              met: item.met === 1 || item.met === true,
            }))
          : null;

        return {
          questionId: question.id,
          part: question.part,
          skipped: skippedQuestionIds.has(question.id),
          response,
          requiredPoints,
        };
      }),
    );

    const domainScoresRaw =
      (examResult.domainScores?.subscores as { area?: unknown; score?: unknown }[] | undefined) ??
      [];
    const domainScores: ReportDomainScore[] = domainScoresRaw
      .filter((item) => typeof item.area === 'string' && typeof item.score === 'number')
      .map((item) => ({ area: item.area as string, score: item.score as number }));

    const violationCounts = new Map<string, ReportViolation>();
    for (const event of events) {
      const key = `${event.eventType}:${event.severity}`;
      const existing = violationCounts.get(key);
      if (existing) {
        existing.count += 1;
      } else {
        violationCounts.set(key, {
          eventType: event.eventType,
          severity: event.severity,
          count: 1,
        });
      }
    }

    return {
      examResultId: examResult.id,
      examSessionId: session.id,
      candidateName: `${user.firstName} ${user.lastName}`,
      startedAt: session.startedAt,
      finalGrade: examResult.finalGrade,
      percentile: examResult.percentile,
      domainScores,
      tasks,
      violations: Array.from(violationCounts.values()),
    };
  }
}
