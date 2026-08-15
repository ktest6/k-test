import { Body, Controller, Get, HttpCode, HttpStatus, Param, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { QuestionService } from '../../question/application/services/question.service';
import { ChecklistItemResponseDto } from '../application/dto/checklist-item-response.dto';
import { DocumentResponseDto } from '../application/dto/document-response.dto';
import { GeneratedQuestionResponseDto } from '../application/dto/generated-question-response.dto';
import { UploadDocumentDto } from '../application/dto/upload-document.dto';
import { UploadDocumentResponseDto } from '../application/dto/upload-document-response.dto';
import { DocumentService } from '../application/services/document.service';

@ApiBearerAuth()
@ApiTags('Admin - Document')
@ApiCommonErrorResponses()
@Roles(Role.ADMIN)
@Controller('admin/documents')
export class DocumentController {
  constructor(
    private readonly documentService: DocumentService,
    private readonly questionService: QuestionService,
  ) {}

  @Post()
  @HttpCode(HttpStatus.ACCEPTED)
  @ApiOperation({
    summary: '문제 원본 서류 업로드',
    description:
      '파일 자체는 받지 않는다 — 프론트가 Supabase Storage에 직접 올린 뒤 그 경로(filePath)만 전달한다. ' +
      '문서 레코드만 만들고 즉시 202로 응답하며, 실제 문항 생성은 document.uploaded 이벤트를 받아 백그라운드로 처리한다.',
  })
  @ApiStandardResponse(UploadDocumentResponseDto, { status: 202, message: '서류 업로드 접수' })
  async upload(
    @CurrentUser() user: AuthenticatedUser,
    @Body() dto: UploadDocumentDto,
  ): Promise<UploadDocumentResponseDto> {
    const document = await this.documentService.upload(user.id, dto);
    return { id: document.id, status: document.status };
  }

  @Get(':id')
  @ApiOperation({
    summary: '문서 상태 조회',
    description: 'UPLOADED/PROCESSING/COMPLETED/FAILED 중 하나. 폴링용.',
  })
  @ApiStandardResponse(DocumentResponseDto, { message: '문서 조회 성공' })
  async findById(@Param('id') id: string): Promise<DocumentResponseDto> {
    const document = await this.documentService.findById(id);
    return {
      id: document.id,
      filePath: document.filePath,
      fileName: document.fileName,
      status: document.status,
      errorMessage: document.errorMessage,
      createdAt: document.createdAt,
    };
  }

  @Get(':id/questions')
  @ApiOperation({ summary: '해당 문서로 생성된 문항 목록 조회 (체크리스트 포함)' })
  @ApiStandardResponse(GeneratedQuestionResponseDto, {
    isArray: true,
    message: '문항 목록 조회 성공',
  })
  async getQuestions(@Param('id') id: string): Promise<GeneratedQuestionResponseDto[]> {
    await this.documentService.findById(id);
    const questions = await this.questionService.findByDocumentId(id);
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
