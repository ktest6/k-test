import { Body, Controller, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { CreateScoreDto } from '../application/dto/create-score.dto';
import { ScoreResponseDto } from '../application/dto/score-response.dto';
import { ScoringService } from '../application/services/scoring.service';

@ApiBearerAuth()
@ApiTags('Admin - Scoring')
@ApiCommonErrorResponses()
@Roles(Role.ADMIN)
@Controller('scoring')
export class AdminScoringController {
  constructor(private readonly scoringService: ScoringService) {}

  @Post()
  @ApiOperation({ summary: '채점 결과 등록 (관리자/채점 파이프라인)' })
  @ApiStandardResponse(ScoreResponseDto, { status: 201, message: 'Score recorded' })
  record(@Body() dto: CreateScoreDto): Promise<ScoreResponseDto> {
    return this.scoringService.record(dto);
  }
}
