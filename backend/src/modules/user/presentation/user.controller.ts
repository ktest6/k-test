import { Body, Controller, Get, Param, Patch } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { UpdateUserDto } from '../application/dto/update-user.dto';
import { UserResponseDto } from '../application/dto/user-response.dto';
import { UserService } from '../application/services/user.service';

@ApiBearerAuth()
@ApiTags('User')
@Controller('users')
export class UserController {
  constructor(private readonly userService: UserService) {}

  @Get('me')
  @ApiOperation({ summary: '내 프로필 조회' })
  getMyProfile(@CurrentUser() user: AuthenticatedUser): Promise<UserResponseDto> {
    return this.userService.findById(user.id);
  }

  @Patch('me')
  @ApiOperation({ summary: '내 프로필 수정' })
  updateMyProfile(
    @CurrentUser() user: AuthenticatedUser,
    @Body() dto: UpdateUserDto,
  ): Promise<UserResponseDto> {
    return this.userService.update(user.id, dto);
  }

  @Get()
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '전체 사용자 목록 (관리자)' })
  list(): Promise<UserResponseDto[]> {
    return this.userService.list();
  }

  @Get(':id')
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '사용자 상세 조회 (관리자)' })
  findById(@Param('id') id: string): Promise<UserResponseDto> {
    return this.userService.findById(id);
  }
}
