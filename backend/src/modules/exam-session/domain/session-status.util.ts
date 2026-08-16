import { ExamSession } from './entities/exam-session.entity';
import { SessionStatus } from './enums/session-status.enum';

/** 응시 기간이 지났는데 세션이 아직 INPROGRESS로 저장돼 있으면 EXPIRED로 계산해서 보여준다(저장은 안 함). */
export function computeSessionStatus(session: ExamSession, examCloseAt: Date): SessionStatus {
  const isPastDeadline = Date.now() > examCloseAt.getTime();
  return session.status === SessionStatus.INPROGRESS && isPastDeadline
    ? SessionStatus.EXPIRED
    : session.status;
}
