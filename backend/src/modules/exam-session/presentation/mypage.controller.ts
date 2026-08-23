import { Controller, Get, Param } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { MyExamStatusResponseDto } from '../application/dto/my-exam-status-response.dto';
import { ReportResponseDto } from '../application/dto/report-response.dto';
import { ExamSessionService } from '../application/services/exam-session.service';
import { MypageReportService } from '../application/services/mypage-report.service';

@ApiBearerAuth()
@ApiTags('Mypage')
@ApiCommonErrorResponses()
@Controller('mypage')
export class MypageController {
  constructor(
    private readonly examSessionService: ExamSessionService,
    private readonly mypageReportService: MypageReportService,
  ) {}

  @Get()
  @ApiOperation({
    summary: '내 응시 시험 현황 조회',
    description:
      '이 사용자가 시작한 적 있는 세션들을 회차 정보와 함께 내려준다(항시 응시 체제라 ' +
      '"신청만 하고 시작 안 함" 같은 중간 상태는 없다 — 목록에 있다는 것 자체가 시작했다는 뜻). ' +
      'examSessionId는 참고용 값이며, [이어서 풀기]는 이 값을 쓰지 않고 항상 ' +
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
      examSessionId: status.session.id,
      sessionStatus: status.session.status,
      startedAt: status.session.startedAt,
      submittedAt: status.session.submittedAt,
      examResultId: status.examResultId,
      finalGrade: status.finalGrade,
    }));
  }

  @Get('report/:examResultId')
  @ApiOperation({
    summary: '최종 리포트 상세 조회',
    description:
      '최종 등급/영역별 점수/문항별 답변(STT 전사)·체크리스트 충족 여부/부정행위 로그를 ' +
      '한 번에 준다. tasks는 배정된 문항 순서 그대로(=응시 순서)이며, 건너뛴 문항은 명시적 ' +
      '스킵/미응답 구분 없이 skipped:true로만 표시한다. violations는 프런트 직접 감지 신호와 ' +
      'AI 모니터링 감지 신호가 eventType 하나에 섞여서 종류·심각도별 건수로 집계되어 온다.',
  })
  @ApiStandardResponse(ReportResponseDto, { message: '최종 리포트 조회 성공' })
  async getReport(
    @Param('examResultId') examResultId: string,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<ReportResponseDto> {
    return this.mypageReportService.getReport(examResultId, user.id);
  }
}
