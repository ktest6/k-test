import { Body, Controller, Get, Param, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { CreateScoreDto } from '../application/dto/create-score.dto';
import { ScoreResponseDto } from '../application/dto/score-response.dto';
import { ScoringService } from '../application/services/scoring.service';

@ApiBearerAuth()
@ApiTags('Scoring')
@ApiCommonErrorResponses()
@Controller('scoring')
export class ScoringController {
  constructor(private readonly scoringService: ScoringService) {}

  @Post()
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '채점 결과 등록 (관리자/채점 파이프라인)' })
  @ApiStandardResponse(ScoreResponseDto, { status: 201, message: '채점 결과 등록 완료' })
  record(@Body() dto: CreateScoreDto): Promise<ScoreResponseDto> {
    return this.scoringService.record(dto);
  }

  @Get(':answerId')
  @ApiOperation({ summary: '답안별 채점 결과 조회' })
  @ApiStandardResponse(ScoreResponseDto, { message: '채점 결과 조회 성공' })
  findByAnswer(@Param('answerId') answerId: string): Promise<ScoreResponseDto> {
    return this.scoringService.getByAnswerId(answerId);
  }
}
