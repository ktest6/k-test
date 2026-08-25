import { Controller, Get, Param } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { UserResponseDto } from '../application/dto/user-response.dto';
import { UserService } from '../application/services/user.service';

@ApiBearerAuth()
@ApiTags('Admin - User')
@ApiCommonErrorResponses()
@Roles(Role.ADMIN)
@Controller('users')
export class AdminUserController {
  constructor(private readonly userService: UserService) {}

  @Get()
  @ApiOperation({ summary: '전체 사용자 목록 (관리자)' })
  @ApiStandardResponse(UserResponseDto, { isArray: true, message: 'User list retrieved' })
  list(): Promise<UserResponseDto[]> {
    return this.userService.list();
  }

  @Get(':id')
  @ApiOperation({ summary: '사용자 상세 조회 (관리자)' })
  @ApiStandardResponse(UserResponseDto, { message: 'User retrieved' })
  findById(@Param('id') id: string): Promise<UserResponseDto> {
    return this.userService.findById(id);
  }
}
