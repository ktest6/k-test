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
@Controller('tests')
export class TestController {
  constructor(private readonly testService: TestService) {}

  @Post()
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '시험 생성 (관리자)' })
  create(
    @Body() dto: CreateTestDto,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<TestResponseDto> {
    return this.testService.create({ ...dto, createdBy: user.id });
  }

  @Get()
  @ApiOperation({ summary: '시험 목록 조회' })
  list(): Promise<TestResponseDto[]> {
    return this.testService.list();
  }

  @Get(':id')
  @ApiOperation({ summary: '시험 상세 조회' })
  findById(@Param('id') id: string): Promise<TestResponseDto> {
    return this.testService.findById(id);
  }

  @Put(':id')
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '시험 수정 (관리자)' })
  update(@Param('id') id: string, @Body() dto: UpdateTestDto): Promise<TestResponseDto> {
    return this.testService.update(id, dto);
  }

  @Delete(':id')
  @Roles(Role.ADMIN)
  @HttpCode(HttpStatus.NO_CONTENT)
  @ApiOperation({ summary: '시험 삭제 (관리자)' })
  delete(@Param('id') id: string): Promise<void> {
    return this.testService.delete(id);
  }
}
