import { Inject, Injectable } from '@nestjs/common';
import {
  ConflictDomainException,
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { ExamSession } from '../../domain/entities/exam-session.entity';
import { SessionStatus } from '../../domain/enums/session-status.enum';
import {
  EXAM_SESSION_REPOSITORY,
  ExamSessionRepository,
} from '../../domain/exam-session.repository.interface';

/**
 * 세션 소유권 + INPROGRESS 여부만 확인하는 가장 얕은 게이트. 본인인증/이어폰/
 * 시선 캘리브레이션 서비스가 이걸 직접 쓴다 — ExamSessionService는
 * IdCardVerificationService 등에 의존하므로, 거꾸로 검증 서비스가
 * ExamSessionService를 의존하면 순환 참조가 생긴다. 이 서비스는 리포지토리
 * 하나에만 의존해서 그 순환을 끊는다.
 */
@Injectable()
export class ExamSessionAccessService {
  constructor(
    @Inject(EXAM_SESSION_REPOSITORY)
    private readonly examSessionRepository: ExamSessionRepository,
  ) {}

  async assertOwnedInProgress(examSessionId: string, userId: string): Promise<ExamSession> {
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
    return session;
  }
}
