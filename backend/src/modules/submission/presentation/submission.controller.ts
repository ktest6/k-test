import { Body, Controller, Get, Param, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { CreateSubmissionDto } from '../application/dto/create-submission.dto';
import { SubmissionResponseDto } from '../application/dto/submission-response.dto';
import { SubmissionService } from '../application/services/submission.service';

@ApiBearerAuth()
@ApiTags('Submission')
@ApiCommonErrorResponses()
@Controller('submissions')
export class SubmissionController {
  constructor(private readonly submissionService: SubmissionService) {}

  @Post()
  @ApiOperation({ summary: '시험 응시 시작' })
  @ApiStandardResponse(SubmissionResponseDto, { status: 201, message: 'Submission started' })
  start(
    @Body() dto: CreateSubmissionDto,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<SubmissionResponseDto> {
    return this.submissionService.start({ testId: dto.testId, userId: user.id });
  }

  @Get()
  @ApiOperation({ summary: '내 응시 목록 조회' })
  @ApiStandardResponse(SubmissionResponseDto, {
    isArray: true,
    message: 'Submission list retrieved',
  })
  listMine(@CurrentUser() user: AuthenticatedUser): Promise<SubmissionResponseDto[]> {
    return this.submissionService.listMine(user.id);
  }

  @Get(':id')
  @ApiOperation({ summary: '응시 상세 조회' })
  @ApiStandardResponse(SubmissionResponseDto, { message: 'Submission retrieved' })
  findById(@Param('id') id: string): Promise<SubmissionResponseDto> {
    return this.submissionService.findById(id);
  }

  @Post(':id/submit')
  @ApiOperation({ summary: '답안 최종 제출' })
  @ApiStandardResponse(SubmissionResponseDto, { status: 201, message: 'Answer submitted' })
  submit(@Param('id') id: string): Promise<SubmissionResponseDto> {
    return this.submissionService.submit(id);
  }
}
