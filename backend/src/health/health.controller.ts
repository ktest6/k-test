import { Controller, Get } from '@nestjs/common';
import { ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiStandardResponse } from '../common/decorators/api-standard-response.decorator';
import { Public } from '../common/decorators/public.decorator';
import { HealthResponseDto } from './dto/health-response.dto';

@ApiTags('Health')
@Controller('health')
export class HealthController {
  @Public()
  @Get()
  @ApiOperation({ summary: '헬스체크' })
  @ApiStandardResponse(HealthResponseDto, { message: 'Health check successful' })
  check(): HealthResponseDto {
    return { status: 'ok', timestamp: new Date().toISOString() };
  }
}
