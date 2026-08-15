import { Controller, HttpCode, HttpStatus, Param, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { SubmissionResponseDto } from '../application/dto/submission-response.dto';
import { SubmissionService } from '../application/services/submission.service';

@ApiBearerAuth()
@ApiTags('Admin - Submission')
@ApiCommonErrorResponses()
@Roles(Role.ADMIN)
@Controller('submissions')
export class AdminSubmissionController {
  constructor(private readonly submissionService: SubmissionService) {}

  @Post(':id/disqualify')
  @HttpCode(HttpStatus.OK)
  @ApiOperation({ summary: '수동 실격 처리 (관리자, 자동 정책 외 개입)' })
  @ApiStandardResponse(SubmissionResponseDto, { message: '실격 처리 완료' })
  disqualify(@Param('id') id: string): Promise<SubmissionResponseDto> {
    return this.submissionService.disqualify(id);
  }
}
