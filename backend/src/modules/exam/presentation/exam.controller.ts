import { Body, Controller, Delete, Get, HttpCode, HttpStatus, Param, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiNoContentResponse, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { Exam } from '../domain/entities/exam.entity';
import { computeExamStatus } from '../domain/exam-status.util';
import { ApplyExamResponseDto } from '../application/dto/apply-exam-response.dto';
import { CreateExamDto } from '../application/dto/create-exam.dto';
import { ExamAdminResponseDto } from '../application/dto/exam-admin-response.dto';
import { ExamResponseDto } from '../application/dto/exam-response.dto';
import { ExamApplicationService } from '../application/services/exam-application.service';
import { ExamService } from '../application/services/exam.service';

@ApiBearerAuth()
@ApiTags('Exam')
@ApiCommonErrorResponses()
@Controller('exams')
export class ExamController {
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
    return (await this.toResponse(exam, Role.ADMIN)) as ExamAdminResponseDto;
  }

  @Get()
  @ApiOperation({
    summary: '회차 목록 조회',
    description: '관리자로 조회하면 capacity(정원)/applicantCount(신청 인원)가 추가로 포함된다.',
  })
  @ApiStandardResponse(ExamAdminResponseDto, { isArray: true, message: '회차 목록 조회 성공' })
  async list(
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<(ExamResponseDto | ExamAdminResponseDto)[]> {
    const exams = await this.examService.list();
    return Promise.all(exams.map((exam) => this.toResponse(exam, user.role)));
  }

  @Get(':id')
  @ApiOperation({
    summary: '회차 상세 조회',
    description: '관리자로 조회하면 capacity(정원)/applicantCount(신청 인원)가 추가로 포함된다.',
  })
  @ApiStandardResponse(ExamAdminResponseDto, { message: '회차 조회 성공' })
  async findById(
    @Param('id') id: string,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<ExamResponseDto | ExamAdminResponseDto> {
    const exam = await this.examService.findById(id);
    return this.toResponse(exam, user.role);
  }

  @Post(':id/apply')
  @ApiOperation({
    summary: '회차 신청',
    description: '신청 접수 기간이 아니거나, 이미 신청했거나, 정원이 찼으면 409.',
  })
  @ApiStandardResponse(ApplyExamResponseDto, { status: 201, message: '회차 신청 완료' })
  async apply(
    @Param('id') id: string,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<ApplyExamResponseDto> {
    const application = await this.examApplicationService.apply(id, user.id);
    return { id: application.id, examId: application.examId, appliedAt: application.appliedAt };
  }

  @Delete(':id/apply')
  @HttpCode(HttpStatus.NO_CONTENT)
  @ApiOperation({ summary: '회차 신청 취소' })
  @ApiNoContentResponse({ description: '취소 성공 (바디 없음)' })
  async cancelApplication(
    @Param('id') id: string,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<void> {
    await this.examApplicationService.cancel(id, user.id);
  }

  /** capacity/applicantCount는 관리자에게만 노출 — 응답 DTO 자체를 role에 따라 다르게 만든다. */
  private async toResponse(
    exam: Exam,
    role: Role,
  ): Promise<ExamResponseDto | ExamAdminResponseDto> {
    const base: ExamResponseDto = {
      id: exam.id,
      roundName: exam.roundName,
      applicationOpenAt: exam.applicationOpenAt,
      applicationCloseAt: exam.applicationCloseAt,
      openAt: exam.openAt,
      closeAt: exam.closeAt,
      status: computeExamStatus(exam.openAt, exam.closeAt),
    };
    if (role !== Role.ADMIN) {
      return base;
    }

    const applicantCount = await this.examApplicationService.countActive(exam.id);
    return { ...base, capacity: exam.capacity, applicantCount };
  }
}
