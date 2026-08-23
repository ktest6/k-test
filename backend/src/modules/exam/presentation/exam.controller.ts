import { Controller, Get, Param } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { ExamResponseDto } from '../application/dto/exam-response.dto';
import { ExamService } from '../application/services/exam.service';

@ApiBearerAuth()
@ApiTags('Exam')
@ApiCommonErrorResponses()
@Controller('exams')
export class ExamController {
  constructor(private readonly examService: ExamService) {}

  @Get()
  @ApiOperation({ summary: '회차 목록 조회' })
  @ApiStandardResponse(ExamResponseDto, { isArray: true, message: '회차 목록 조회 성공' })
  async list(): Promise<ExamResponseDto[]> {
    const exams = await this.examService.list();
    return exams.map((exam) => this.toResponse(exam));
  }

  @Get(':id')
  @ApiOperation({ summary: '회차 상세 조회' })
  @ApiStandardResponse(ExamResponseDto, { message: '회차 조회 성공' })
  async findById(@Param('id') id: string): Promise<ExamResponseDto> {
    const exam = await this.examService.findById(id);
    return this.toResponse(exam);
  }

  private toResponse(exam: { id: string; roundName: string; createdAt: Date }): ExamResponseDto {
    return { id: exam.id, roundName: exam.roundName, createdAt: exam.createdAt };
  }
}
