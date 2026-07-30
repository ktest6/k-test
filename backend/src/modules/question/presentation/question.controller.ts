import { Body, Controller, Delete, Get, Param, Post, Put } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { CreateQuestionDto } from '../application/dto/create-question.dto';
import { DeleteQuestionResponseDto } from '../application/dto/delete-question-response.dto';
import { QuestionResponseDto } from '../application/dto/question-response.dto';
import { UpdateQuestionDto } from '../application/dto/update-question.dto';
import { QuestionService } from '../application/services/question.service';

@ApiBearerAuth()
@ApiTags('Question')
@ApiCommonErrorResponses()
@Controller()
export class QuestionController {
  constructor(private readonly questionService: QuestionService) {}

  @Post('tests/:testId/questions')
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '문제 생성 (관리자)' })
  @ApiStandardResponse(QuestionResponseDto, { status: 201, message: '문제 생성 완료' })
  create(
    @Param('testId') testId: string,
    @Body() dto: CreateQuestionDto,
  ): Promise<QuestionResponseDto> {
    return this.questionService.create({ ...dto, testId });
  }

  @Get('tests/:testId/questions')
  @ApiOperation({ summary: '시험별 문제 목록 조회' })
  @ApiStandardResponse(QuestionResponseDto, { isArray: true, message: '문제 목록 조회 성공' })
  listByTest(@Param('testId') testId: string): Promise<QuestionResponseDto[]> {
    return this.questionService.listByTestId(testId);
  }

  @Get('questions/:id')
  @ApiOperation({ summary: '문제 상세 조회' })
  @ApiStandardResponse(QuestionResponseDto, { message: '문제 조회 성공' })
  findById(@Param('id') id: string): Promise<QuestionResponseDto> {
    return this.questionService.findById(id);
  }

  @Put('questions/:id')
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '문제 수정 (관리자)' })
  @ApiStandardResponse(QuestionResponseDto, { message: '문제 수정 완료' })
  update(@Param('id') id: string, @Body() dto: UpdateQuestionDto): Promise<QuestionResponseDto> {
    return this.questionService.update(id, dto);
  }

  @Delete('questions/:id')
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '문제 삭제 (관리자)' })
  @ApiStandardResponse(DeleteQuestionResponseDto, { message: '문제가 삭제되었습니다.' })
  async delete(@Param('id') id: string): Promise<DeleteQuestionResponseDto> {
    await this.questionService.delete(id);
    return { id };
  }
}
