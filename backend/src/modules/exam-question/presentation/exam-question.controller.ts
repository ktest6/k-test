import { Body, Controller, Delete, Get, Param, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { AssignedQuestionResponseDto } from '../application/dto/assigned-question-response.dto';
import { AssignQuestionDto } from '../application/dto/assign-question.dto';
import { ChecklistItemResponseDto } from '../application/dto/checklist-item-response.dto';
import { ExamQuestionResponseDto } from '../application/dto/exam-question-response.dto';
import { UnassignQuestionResponseDto } from '../application/dto/unassign-question-response.dto';
import { ExamQuestionService } from '../application/services/exam-question.service';

@ApiBearerAuth()
@ApiTags('Admin - Exam Question')
@ApiCommonErrorResponses()
@Roles(Role.ADMIN)
@Controller('exams/:examId/questions')
export class ExamQuestionController {
  constructor(private readonly examQuestionService: ExamQuestionService) {}

  @Post()
  @ApiOperation({
    summary: '회차에 문항 배정',
    description: '같은 문항을 이미 배정했으면 409. 문항 하나를 여러 회차에 배정할 수 있다.',
  })
  @ApiStandardResponse(ExamQuestionResponseDto, { status: 201, message: '문항 배정 완료' })
  async assign(
    @Param('examId') examId: string,
    @Body() dto: AssignQuestionDto,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<ExamQuestionResponseDto> {
    const assignment = await this.examQuestionService.assign(examId, dto.questionId, user.id);
    return {
      id: assignment.id,
      examId: assignment.examId,
      questionId: assignment.questionId,
      createdAt: assignment.createdAt,
    };
  }

  @Delete(':questionId')
  @ApiOperation({ summary: '회차에서 문항 배정 해제' })
  @ApiStandardResponse(UnassignQuestionResponseDto, { message: '문항 배정이 해제되었습니다.' })
  async unassign(
    @Param('examId') examId: string,
    @Param('questionId') questionId: string,
  ): Promise<UnassignQuestionResponseDto> {
    await this.examQuestionService.unassign(examId, questionId);
    return { examId, questionId };
  }

  @Get()
  @ApiOperation({ summary: '회차에 배정된 문항 목록 조회 (체크리스트 포함)' })
  @ApiStandardResponse(AssignedQuestionResponseDto, {
    isArray: true,
    message: '배정된 문항 목록 조회 성공',
  })
  async list(@Param('examId') examId: string): Promise<AssignedQuestionResponseDto[]> {
    const questions = await this.examQuestionService.listAssignedQuestions(examId);
    return questions.map((question) => ({
      id: question.id,
      part: question.part,
      content: question.content as unknown as Record<string, unknown>,
      checklistItems: question.checklistItems.map((item): ChecklistItemResponseDto => ({
        id: item.id,
        code: item.code,
        description: item.description,
        weight: item.weight,
      })),
    }));
  }
}
