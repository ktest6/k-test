import { Body, Controller, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { computeExamStatus } from '../domain/exam-status.util';
import { CreateExamDto } from '../application/dto/create-exam.dto';
import { ExamAdminResponseDto } from '../application/dto/exam-admin-response.dto';
import { ExamApplicationService } from '../application/services/exam-application.service';
import { ExamService } from '../application/services/exam.service';

@ApiBearerAuth()
@ApiTags('Admin - Exam')
@ApiCommonErrorResponses()
@Controller('exams')
export class AdminExamController {
  constructor(
    private readonly examService: ExamService,
    private readonly examApplicationService: ExamApplicationService,
  ) {}

  @Post()
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '회차 추가 (관리자)' })
  @ApiStandardResponse(ExamAdminResponseDto, { status: 201, message: '회차 추가 완료' })
  async create(@Body() dto: CreateExamDto): Promise<ExamAdminResponseDto> {
    const exam = await this.examService.create({
      applicationOpenAt: new Date(dto.applicationOpenAt),
      applicationCloseAt: new Date(dto.applicationCloseAt),
      openAt: new Date(dto.openAt),
      closeAt: new Date(dto.closeAt),
      capacity: dto.capacity,
    });
    const applicantCount = await this.examApplicationService.countActive(exam.id);
    return {
      id: exam.id,
      roundName: exam.roundName,
      applicationOpenAt: exam.applicationOpenAt,
      applicationCloseAt: exam.applicationCloseAt,
      openAt: exam.openAt,
      closeAt: exam.closeAt,
      status: computeExamStatus(exam.openAt, exam.closeAt),
      capacity: exam.capacity,
      applicantCount,
    };
  }
}
