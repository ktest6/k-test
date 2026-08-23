import { Controller, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { ExamResponseDto } from '../application/dto/exam-response.dto';
import { ExamService } from '../application/services/exam.service';

@ApiBearerAuth()
@ApiTags('Admin - Exam')
@ApiCommonErrorResponses()
@Controller('exams')
export class AdminExamController {
  constructor(private readonly examService: ExamService) {}

  @Post()
  @Roles(Role.ADMIN)
  @ApiOperation({
    summary: '회차 추가 (관리자)',
    description: '별도 입력값 없음 — roundName은 서버가 자동 생성한다(예: 202601).',
  })
  @ApiStandardResponse(ExamResponseDto, { status: 201, message: '회차 추가 완료' })
  async create(): Promise<ExamResponseDto> {
    const exam = await this.examService.create();
    return { id: exam.id, roundName: exam.roundName, createdAt: exam.createdAt };
  }
}
