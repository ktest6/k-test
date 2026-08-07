import { Inject, Injectable } from '@nestjs/common';
import {
  ConflictDomainException,
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
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

export interface ExamSessionStatusResult {
  session: ExamSession;
  /** 응시 기간이 지났는데 아직 INPROGRESS로 남아있으면 EXPIRED로 계산해서 보여준다(저장은 안 함). */
  status: SessionStatus;
  remainingSeconds: number;
}

@Injectable()
export class ExamSessionService {
  constructor(
    @Inject(EXAM_SESSION_REPOSITORY) private readonly examSessionRepository: ExamSessionRepository,
    private readonly examService: ExamService,
    private readonly examApplicationService: ExamApplicationService,
    private readonly idCardVerificationService: IdCardVerificationService,
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
      if (existing.status === SessionStatus.INPROGRESS) {
        return existing;
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

    return { session, status, remainingSeconds };
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
