import { Controller, Get } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { AiHealthResponseDto } from '../application/dto/ai-health-response.dto';
import { AiService } from '../application/services/ai.service';

@ApiBearerAuth()
@ApiTags('AI')
@ApiCommonErrorResponses()
@Controller('ai')
export class AiController {
  constructor(private readonly aiService: AiService) {}

  @Get('health')
  @ApiOperation({ summary: 'AI provider 연결 상태 확인' })
  @ApiStandardResponse(AiHealthResponseDto, { message: 'AI status retrieved' })
  getHealth(): Promise<AiHealthResponseDto> {
    return this.aiService.getStatus();
  }
}
