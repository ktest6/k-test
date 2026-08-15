import { Controller, Get, Param } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { ScoreResponseDto } from '../application/dto/score-response.dto';
import { ScoringService } from '../application/services/scoring.service';

@ApiBearerAuth()
@ApiTags('Scoring')
@ApiCommonErrorResponses()
@Controller('scoring')
export class ScoringController {
  constructor(private readonly scoringService: ScoringService) {}

  @Get(':answerId')
  @ApiOperation({ summary: '답안별 채점 결과 조회' })
  @ApiStandardResponse(ScoreResponseDto, { message: '채점 결과 조회 성공' })
  findByAnswer(@Param('answerId') answerId: string): Promise<ScoreResponseDto> {
    return this.scoringService.getByAnswerId(answerId);
  }
}
