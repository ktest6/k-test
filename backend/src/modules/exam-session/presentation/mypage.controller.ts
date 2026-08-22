import { Controller, Get } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { MyExamStatusResponseDto } from '../application/dto/my-exam-status-response.dto';
import { ExamSessionService } from '../application/services/exam-session.service';

@ApiBearerAuth()
@ApiTags('Mypage')
@ApiCommonErrorResponses()
@Controller('mypage')
export class MypageController {
  constructor(private readonly examSessionService: ExamSessionService) {}

  @Get()
  @ApiOperation({
    summary: '내 응시 시험 현황 조회',
    description:
      '신청한 회차별로 세션 상태를 함께 내려준다. 시험을 시작한 적 있으면 그 세션 상태 그대로, ' +
      '시작한 적 없고 마감 1시간 전 시작 데드라인도 지났으면 examSessionId는 null이고 ' +
      'sessionStatus는 EXPIRED(신청만 하고 응시 기회를 놓친 경우), 그 전이면 session 관련 필드는 ' +
      '전부 null이다. examSessionId는 참고용 값이며, [이어서 풀기]는 이 값을 쓰지 않고 항상 ' +
      'POST /exams/:id/sessions를 다시 호출해야 한다 — 재개 남용 방지 카운트가 그 호출로만 세어지기 때문이다.',
  })
  @ApiStandardResponse(MyExamStatusResponseDto, {
    isArray: true,
    message: '내 응시 시험 현황 조회 성공',
  })
  async listMine(@CurrentUser() user: AuthenticatedUser): Promise<MyExamStatusResponseDto[]> {
    const statuses = await this.examSessionService.listMine(user.id);
    return statuses.map((status) => ({
      examId: status.exam.id,
      roundName: status.exam.roundName,
      openAt: status.exam.openAt,
      closeAt: status.exam.closeAt,
      examStatus: status.examStatus,
      appliedAt: status.appliedAt,
      examSessionId: status.session?.id ?? null,
      sessionStatus: status.session?.status ?? null,
    }));
  }
}
