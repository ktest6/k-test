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
import { ApiBearerAuth, ApiNoContentResponse, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { CreateTestDto } from '../application/dto/create-test.dto';
import { TestResponseDto } from '../application/dto/test-response.dto';
import { UpdateTestDto } from '../application/dto/update-test.dto';
import { TestService } from '../application/services/test.service';

@ApiBearerAuth()
@ApiTags('Test')
@ApiCommonErrorResponses()
@Controller('tests')
export class TestController {
  constructor(private readonly testService: TestService) {}

  @Post()
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '시험 생성 (관리자)' })
  @ApiStandardResponse(TestResponseDto, { status: 201, message: '시험 생성 완료' })
  create(
    @Body() dto: CreateTestDto,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<TestResponseDto> {
    return this.testService.create({ ...dto, createdBy: user.id });
  }

  @Get()
  @ApiOperation({ summary: '시험 목록 조회' })
  @ApiStandardResponse(TestResponseDto, { isArray: true, message: '시험 목록 조회 성공' })
  list(): Promise<TestResponseDto[]> {
    return this.testService.list();
  }

  @Get(':id')
  @ApiOperation({ summary: '시험 상세 조회' })
  @ApiStandardResponse(TestResponseDto, { message: '시험 조회 성공' })
  findById(@Param('id') id: string): Promise<TestResponseDto> {
    return this.testService.findById(id);
  }

  @Put(':id')
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '시험 수정 (관리자)' })
  @ApiStandardResponse(TestResponseDto, { message: '시험 수정 완료' })
  update(@Param('id') id: string, @Body() dto: UpdateTestDto): Promise<TestResponseDto> {
    return this.testService.update(id, dto);
  }

  @Delete(':id')
  @Roles(Role.ADMIN)
  @HttpCode(HttpStatus.NO_CONTENT)
  @ApiOperation({ summary: '시험 삭제 (관리자)' })
  @ApiNoContentResponse({ description: '삭제 성공 (바디 없음)' })
  delete(@Param('id') id: string): Promise<void> {
    return this.testService.delete(id);
  }
}
