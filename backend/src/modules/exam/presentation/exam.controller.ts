import { Body, Controller, Get, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { Exam } from '../domain/entities/exam.entity';
import { computeExamStatus } from '../domain/exam-status.util';
import { CreateExamDto } from '../application/dto/create-exam.dto';
import { ExamAdminResponseDto } from '../application/dto/exam-admin-response.dto';
import { ExamResponseDto } from '../application/dto/exam-response.dto';
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
    return this.toResponse(exam, Role.ADMIN) as ExamAdminResponseDto;
  }

  @Get()
  @ApiOperation({
    summary: '회차 목록 조회',
    description: '관리자로 조회하면 capacity(정원)가 추가로 포함된다.',
  })
  @ApiStandardResponse(ExamAdminResponseDto, { isArray: true, message: '회차 목록 조회 성공' })
  async list(
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<(ExamResponseDto | ExamAdminResponseDto)[]> {
    const exams = await this.examService.list();
    return exams.map((exam) => this.toResponse(exam, user.role));
  }

  /** capacity(정원)는 관리자에게만 노출 — 응답 DTO 자체를 role에 따라 다르게 만든다. */
  private toResponse(exam: Exam, role: Role): ExamResponseDto | ExamAdminResponseDto {
    const base: ExamResponseDto = {
      id: exam.id,
      roundName: exam.roundName,
      openAt: exam.openAt,
      closeAt: exam.closeAt,
      status: computeExamStatus(exam.openAt, exam.closeAt),
    };
    return role === Role.ADMIN ? { ...base, capacity: exam.capacity } : base;
  }
}
