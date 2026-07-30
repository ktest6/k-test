import { Body, Controller, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { Exam } from '../domain/entities/exam.entity';
import { computeExamStatus } from '../domain/exam-status.util';
import { CreateExamDto } from '../application/dto/create-exam.dto';
import { ExamAdminResponseDto } from '../application/dto/exam-admin-response.dto';
import { ExamService } from '../application/services/exam.service';

@ApiBearerAuth()
@ApiTags('Exam')
@ApiCommonErrorResponses()
@Controller('exams')
export class ExamController {
  constructor(private readonly examService: ExamService) {}

  @Post()
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '회차 추가 (관리자)' })
  @ApiStandardResponse(ExamAdminResponseDto, { status: 201, message: '회차 추가 완료' })
  async create(@Body() dto: CreateExamDto): Promise<ExamAdminResponseDto> {
    const exam = await this.examService.create({
      roundName: dto.roundName,
      openAt: new Date(dto.openAt),
      closeAt: new Date(dto.closeAt),
      capacity: dto.capacity,
    });
    return this.toAdminResponse(exam);
  }

  private toAdminResponse(exam: Exam): ExamAdminResponseDto {
    return {
      id: exam.id,
      roundName: exam.roundName,
      openAt: exam.openAt,
      closeAt: exam.closeAt,
      status: computeExamStatus(exam.openAt, exam.closeAt),
      capacity: exam.capacity,
    };
  }
}
