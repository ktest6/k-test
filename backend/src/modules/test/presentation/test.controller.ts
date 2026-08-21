import { Controller, Post } from '@nestjs/common';
import { ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { Public } from '../../../common/decorators/public.decorator';
import { ResetSessionResponseDto } from '../application/dto/reset-session-response.dto';
import { TestResetService } from '../application/services/test-reset.service';

@ApiTags('Test (개발 전용)')
@Controller('test')
export class TestController {
  constructor(private readonly testResetService: TestResetService) {}

  @Public()
  @Post('reset-session')
  @ApiOperation({
    summary: '[테스트 전용] 모든 응시 세션을 INPROGRESS로 리셋',
    description:
      '인증 없이 호출 가능. 반복 테스트 중 BLOCKED/DISQUALIFIED/SUBMITTED로 막힌 세션을 ' +
      '되돌리기 위한 개발용 유틸리티다. 프로덕션 환경(NODE_ENV=production)에서는 항상 거부된다. ' +
      '실제 서비스 배포 전 이 컨트롤러/모듈 자체를 반드시 제거할 것.',
  })
  @ApiStandardResponse(ResetSessionResponseDto, { message: '세션 리셋 완료' })
  async resetSessions(): Promise<ResetSessionResponseDto> {
    const resetCount = await this.testResetService.resetAllSessionsToInProgress();
    return { resetCount };
  }
}
