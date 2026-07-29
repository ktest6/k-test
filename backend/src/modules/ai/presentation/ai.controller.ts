import { Controller, Get } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { AiHealthResponseDto } from '../application/dto/ai-health-response.dto';
import { AiService } from '../application/services/ai.service';

@ApiBearerAuth()
@ApiTags('AI')
@Controller('ai')
export class AiController {
  constructor(private readonly aiService: AiService) {}

  @Get('health')
  @ApiOperation({ summary: 'AI provider 연결 상태 확인' })
  getHealth(): Promise<AiHealthResponseDto> {
    return this.aiService.getStatus();
  }
}
