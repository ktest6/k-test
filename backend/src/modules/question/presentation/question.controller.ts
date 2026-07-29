import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  HttpStatus,
  Param,
  Post,
  Put,
} from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { CreateQuestionDto } from '../application/dto/create-question.dto';
import { QuestionResponseDto } from '../application/dto/question-response.dto';
import { UpdateQuestionDto } from '../application/dto/update-question.dto';
import { QuestionService } from '../application/services/question.service';

@ApiBearerAuth()
@ApiTags('Question')
@Controller()
export class QuestionController {
  constructor(private readonly questionService: QuestionService) {}

  @Post('tests/:testId/questions')
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '문제 생성 (관리자)' })
  create(
    @Param('testId') testId: string,
    @Body() dto: CreateQuestionDto,
  ): Promise<QuestionResponseDto> {
    return this.questionService.create({ ...dto, testId });
  }

  @Get('tests/:testId/questions')
  @ApiOperation({ summary: '시험별 문제 목록 조회' })
  listByTest(@Param('testId') testId: string): Promise<QuestionResponseDto[]> {
    return this.questionService.listByTestId(testId);
  }

  @Get('questions/:id')
  @ApiOperation({ summary: '문제 상세 조회' })
  findById(@Param('id') id: string): Promise<QuestionResponseDto> {
    return this.questionService.findById(id);
  }

  @Put('questions/:id')
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '문제 수정 (관리자)' })
  update(@Param('id') id: string, @Body() dto: UpdateQuestionDto): Promise<QuestionResponseDto> {
    return this.questionService.update(id, dto);
  }

  @Delete('questions/:id')
  @Roles(Role.ADMIN)
  @HttpCode(HttpStatus.NO_CONTENT)
  @ApiOperation({ summary: '문제 삭제 (관리자)' })
  delete(@Param('id') id: string): Promise<void> {
    return this.questionService.delete(id);
  }
}
