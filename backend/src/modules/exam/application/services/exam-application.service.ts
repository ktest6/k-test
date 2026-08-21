import { Inject, Injectable } from '@nestjs/common';
import {
  ConflictDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { SessionStatus } from '../../../exam-session/domain/enums/session-status.enum';
import {
  EXAM_SESSION_REPOSITORY,
  ExamSessionRepository,
} from '../../../exam-session/domain/exam-session.repository.interface';
import { ExamApplication } from '../../domain/entities/exam-application.entity';
import {
  EXAM_APPLICATION_REPOSITORY,
  ExamApplicationRepository,
} from '../../domain/exam-application.repository.interface';
import { isApplicationOpen } from '../../domain/exam-status.util';
import { ExamService } from './exam.service';

/** 이 상태의 세션이 있으면 신청 취소를 막는다 — 특히 DISQUALIFIED/BLOCKED는 취소 후
 * 재신청으로 실격/차단을 우회하는 걸 막기 위함, INPROGRESS는 응시 중 취소로 인한
 * 세션-신청 불일치를 막기 위함이다. */
const CANCEL_BLOCKED_SESSION_STATUSES = new Set<SessionStatus>([
  SessionStatus.INPROGRESS,
  SessionStatus.BLOCKED,
  SessionStatus.DISQUALIFIED,
]);

@Injectable()
export class ExamApplicationService {
  constructor(
    private readonly examService: ExamService,
    @Inject(EXAM_APPLICATION_REPOSITORY)
    private readonly examApplicationRepository: ExamApplicationRepository,
    @Inject(EXAM_SESSION_REPOSITORY)
    private readonly examSessionRepository: ExamSessionRepository,
  ) {}

  async apply(examId: string, userId: string): Promise<ExamApplication> {
    const exam = await this.examService.findById(examId);

    if (!isApplicationOpen(exam.applicationOpenAt, exam.applicationCloseAt)) {
      throw new ConflictDomainException('지금은 신청 기간이 아닙니다.');
    }

    const existing = await this.examApplicationRepository.findActiveByExamAndUser(examId, userId);
    if (existing) {
      throw new ConflictDomainException('이미 신청한 회차입니다.');
    }

    // 정원 체크와 실제 insert 사이에 이론적으로 경쟁 상태가 있을 수 있다
    // (동시에 두 요청이 마지막 한 자리를 두고 둘 다 통과). 중복 신청은
    // DB의 부분 유니크 인덱스가 완전히 막아주지만, 정원 초과는 이 체크에만
    // 의존한다 — 현재 트래픽 규모에서는 이 정도로 충분하다고 판단.
    const activeCount = await this.examApplicationRepository.countActiveByExam(examId);
    if (activeCount >= exam.capacity) {
      throw new ConflictDomainException('정원이 마감되었습니다.');
    }

    return this.examApplicationRepository.create({ examId, userId });
  }

  async cancel(examId: string, userId: string): Promise<void> {
    const application = await this.examApplicationRepository.findActiveByExamAndUser(
      examId,
      userId,
    );
    if (!application) {
      throw new NotFoundDomainException('신청 내역을 찾을 수 없습니다.');
    }

    const session = await this.examSessionRepository.findByUserAndExam(userId, examId);
    if (session && CANCEL_BLOCKED_SESSION_STATUSES.has(session.status)) {
      throw new ConflictDomainException(
        '이미 시작되었거나 실격·차단된 시험은 신청을 취소할 수 없습니다.',
      );
    }

    await this.examApplicationRepository.cancel(application.id);
  }

  countActive(examId: string): Promise<number> {
    return this.examApplicationRepository.countActiveByExam(examId);
  }

  async hasActiveApplication(examId: string, userId: string): Promise<boolean> {
    const application = await this.examApplicationRepository.findActiveByExamAndUser(
      examId,
      userId,
    );
    return !!application;
  }

  listMine(userId: string): Promise<ExamApplication[]> {
    return this.examApplicationRepository.listActiveByUser(userId);
  }
}
