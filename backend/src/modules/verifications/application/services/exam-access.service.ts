import { Injectable } from '@nestjs/common';
import { ForbiddenDomainException } from '../../../../common/exceptions/domain.exception';
import { ExamApplicationService } from '../../../exam/application/services/exam-application.service';

/**
 * 본인인증은 시험 세션이 만들어지기 전에 끝나야 하므로(세션 존재를 전제로
 * 할 수 없다), tb_exam_session이 아니라 "이 회차에 신청했는가"로 접근
 * 권한을 확인한다. /verifications 아래의 모든 인증 타입(id-card, 추후
 * earphone 등)이 공통으로 쓰는 검증이라 여기서 공유한다.
 */
@Injectable()
export class ExamAccessService {
  constructor(private readonly examApplicationService: ExamApplicationService) {}

  async assertApplied(userId: string, examId: string): Promise<void> {
    const applied = await this.examApplicationService.hasActiveApplication(examId, userId);
    if (!applied) {
      throw new ForbiddenDomainException('신청한 회차가 아닙니다.');
    }
  }
}
