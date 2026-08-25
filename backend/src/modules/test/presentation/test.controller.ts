import { Controller, Post } from '@nestjs/common';
import { ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { Public } from '../../../common/decorators/public.decorator';
import { QuickStartResponseDto } from '../application/dto/quick-start-response.dto';
import { ResetSessionResponseDto } from '../application/dto/reset-session-response.dto';
import { TestQuickStartService } from '../application/services/test-quick-start.service';
import { TestResetService } from '../application/services/test-reset.service';

@ApiTags('Test (개발 전용)')
@Controller('test')
export class TestController {
  constructor(
    private readonly testResetService: TestResetService,
    private readonly testQuickStartService: TestQuickStartService,
  ) {}

  @Public()
  @Post('reset-session')
  @ApiOperation({
    summary: '[테스트 전용] 모든 응시 세션을 INPROGRESS로 리셋',
    description:
      '인증 없이 호출 가능. 반복 테스트 중 BLOCKED/DISQUALIFIED/SUBMITTED로 막힌 세션을 ' +
      '되돌리기 위한 개발용 유틸리티다. 프로덕션 환경(NODE_ENV=production)에서는 항상 거부된다. ' +
      '실제 서비스 배포 전 이 컨트롤러/모듈 자체를 반드시 제거할 것.',
  })
  @ApiStandardResponse(ResetSessionResponseDto, { message: 'Sessions reset' })
  async resetSessions(): Promise<ResetSessionResponseDto> {
    const resetCount = await this.testResetService.resetAllSessionsToInProgress();
    return { resetCount };
  }

  @Public()
  @Post('quick-start')
  @ApiOperation({
    summary: '[테스트 전용] 회원가입·본인인증·이어폰체크 없이 검증된 세션 즉시 생성',
    description:
      '테스트 계정을 새로 만들고(이메일 인증 절차 생략), 응시 세션을 시작한 뒤, 본인인증/' +
      '이어폰체크를 실제로 통과한 것과 동일한 로그를 남겨 verified:true 상태로 만든다. ' +
      '응답의 accessToken으로 바로 GET /exam-sessions/:id/questions부터 시작하면 된다 ' +
      '(모니터링/부정행위 신고 API는 호출하지 않아도 시험 진행에 지장 없음 — 애초에 선택 호출). ' +
      '인증 없이 호출 가능. 프로덕션 환경(NODE_ENV=production)에서는 항상 거부된다. ' +
      '실제 서비스 배포 전 이 컨트롤러/모듈 자체를 반드시 제거할 것.',
  })
  @ApiStandardResponse(QuickStartResponseDto, { status: 201, message: 'Test session ready' })
  async quickStart(): Promise<QuickStartResponseDto> {
    return this.testQuickStartService.quickStart();
  }
}
