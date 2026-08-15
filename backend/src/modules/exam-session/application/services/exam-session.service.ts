import { Inject, Injectable } from '@nestjs/common';
import {
  ConflictDomainException,
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { AnswerService } from '../../../answer/application/services/answer.service';
import { ExamApplicationService } from '../../../exam/application/services/exam-application.service';
import { ExamService } from '../../../exam/application/services/exam.service';
import { ExamStatus } from '../../../exam/domain/enums/exam-status.enum';
import { computeExamStatus } from '../../../exam/domain/exam-status.util';
import { IdCardVerificationService } from '../../../verifications/application/services/id-card-verification.service';
import { ExamSession } from '../../domain/entities/exam-session.entity';
import { SessionStatus } from '../../domain/enums/session-status.enum';
import {
  EXAM_SESSION_REPOSITORY,
  ExamSessionRepository,
} from '../../domain/exam-session.repository.interface';
import { ExamSessionQuestionService } from './exam-session-question.service';

/** 재개(재시작) 시도가 이 횟수에 도달하면 세션을 BLOCKED로 전환하고 더 이상 진행을 막는다. */
const RESUME_ATTEMPT_LIMIT = 3;

export interface ExamSessionStatusResult {
  session: ExamSession;
  /** 응시 기간이 지났는데 아직 INPROGRESS로 남아있으면 EXPIRED로 계산해서 보여준다(저장은 안 함). */
  status: SessionStatus;
  remainingSeconds: number;
  /** 아직 답안이 없는 첫 문항 — 매번 답안 저장 현황으로 계산하며 별도로 저장하지 않는다. 모두 답했거나 진행중이 아니면 null. */
  nextQuestionId: string | null;
}

@Injectable()
export class ExamSessionService {
  constructor(
    @Inject(EXAM_SESSION_REPOSITORY) private readonly examSessionRepository: ExamSessionRepository,
    private readonly examService: ExamService,
    private readonly examApplicationService: ExamApplicationService,
    private readonly idCardVerificationService: IdCardVerificationService,
    private readonly examSessionQuestionService: ExamSessionQuestionService,
    private readonly answerService: AnswerService,
  ) {}

  async start(examId: string, userId: string): Promise<ExamSession> {
    const exam = await this.examService.findById(examId);

    if (computeExamStatus(exam.openAt, exam.closeAt) !== ExamStatus.OPEN) {
      throw new ConflictDomainException('지금은 응시 기간이 아닙니다.');
    }

    const applied = await this.examApplicationService.hasActiveApplication(examId, userId);
    if (!applied) {
      throw new ForbiddenDomainException('신청한 회차가 아닙니다.');
    }

    const verified = await this.idCardVerificationService.hasVerifiedExam(examId, userId);
    if (!verified) {
      throw new ForbiddenDomainException('본인인증을 먼저 완료해야 합니다.');
    }

    const existing = await this.examSessionRepository.findByUserAndExam(userId, examId);
    if (existing) {
      // 중간에 끊겼다가 다시 "시작"을 누른 경우 — 새로 만들지 않고 같은 세션을 이어서 준다.
      // 다만 반복 재접속은 악용(예: 준비/응답 시간 리셋 시도) 신호로 보고 횟수를 제한한다.
      if (existing.status === SessionStatus.INPROGRESS) {
        const nextResumeCount = existing.resumeCount + 1;
        if (nextResumeCount >= RESUME_ATTEMPT_LIMIT) {
          await this.examSessionRepository.updateStatus(existing.id, SessionStatus.BLOCKED);
          throw new ForbiddenDomainException('반복적인 재접속으로 시험 응시가 제한되었습니다.');
        }
        return this.examSessionRepository.updateResumeCount(existing.id, nextResumeCount);
      }
      throw new ConflictDomainException('이미 종료된 시험입니다.');
    }

    return this.examSessionRepository.create({ examId, userId });
  }

  async getStatus(examSessionId: string, userId: string): Promise<ExamSessionStatusResult> {
    const session = await this.examSessionRepository.findById(examSessionId);
    if (!session) {
      throw new NotFoundDomainException(`응시 세션(${examSessionId})을 찾을 수 없습니다.`);
    }
    if (session.userId !== userId) {
      throw new ForbiddenDomainException('세션 소유자가 아닙니다.');
    }

    const exam = await this.examService.findById(session.examId);
    const now = new Date();
    const isPastDeadline = now.getTime() > exam.closeAt.getTime();

    const status =
      session.status === SessionStatus.INPROGRESS && isPastDeadline
        ? SessionStatus.EXPIRED
        : session.status;

    // 세션이 더 이상 진행중이 아니게 된 시점에 본인인증용 얼굴 이미지를 정리한다.
    // 채점 완료 여부와는 무관 — 얼굴 사진은 채점이 아니라 시험 중 모니터링의
    // 동일인 검사에만 쓰였으므로, 세션이 끝나는 순간 더 이상 쓸모가 없다.
    // 멱등한 정리라 상태 조회가 반복돼도 안전하다.
    if (status !== SessionStatus.INPROGRESS) {
      await this.idCardVerificationService.cleanupVerifiedFaceImage(session.examId, userId);
    }

    const remainingSeconds =
      status === SessionStatus.INPROGRESS
        ? Math.max(0, Math.floor((exam.closeAt.getTime() - now.getTime()) / 1000))
        : 0;

    const nextQuestionId =
      status === SessionStatus.INPROGRESS
        ? await this.findNextQuestionId(examSessionId, userId)
        : null;

    return { session, status, remainingSeconds, nextQuestionId };
  }

  /** 세션에 배정된 문항 순서대로, 아직 답안이 없는 첫 문항을 찾는다. */
  private async findNextQuestionId(examSessionId: string, userId: string): Promise<string | null> {
    const [questions, answeredQuestionIds] = await Promise.all([
      this.examSessionQuestionService.listQuestions(examSessionId, userId),
      this.answerService.listAnsweredQuestionIds(examSessionId),
    ]);

    const answered = new Set(answeredQuestionIds);
    const next = questions.find((question) => !answered.has(question.id));
    return next?.id ?? null;
  }

  /** 답안 저장처럼 "지금 실제로 응시 중"이어야만 허용되는 동작들의 공통 게이트. */
  async assertActiveSession(examSessionId: string, userId: string): Promise<ExamSession> {
    const session = await this.examSessionRepository.findById(examSessionId);
    if (!session) {
      throw new NotFoundDomainException(`응시 세션(${examSessionId})을 찾을 수 없습니다.`);
    }
    if (session.userId !== userId) {
      throw new ForbiddenDomainException('세션 소유자가 아닙니다.');
    }
    if (session.status !== SessionStatus.INPROGRESS) {
      throw new ConflictDomainException('이미 종료된 시험입니다.');
    }

    const exam = await this.examService.findById(session.examId);
    if (Date.now() > exam.closeAt.getTime()) {
      throw new ConflictDomainException('이미 종료된 시험입니다.');
    }

    return session;
  }
}
