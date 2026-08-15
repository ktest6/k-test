import { Body, Controller, Get, Patch } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { UpdateUserDto } from '../application/dto/update-user.dto';
import { UserResponseDto } from '../application/dto/user-response.dto';
import { UserService } from '../application/services/user.service';

@ApiBearerAuth()
@ApiTags('User')
@ApiCommonErrorResponses()
@Controller('users')
export class UserController {
  constructor(private readonly userService: UserService) {}

  @Get('me')
  @ApiOperation({ summary: '내 프로필 조회' })
  @ApiStandardResponse(UserResponseDto, { message: '내 프로필 조회 성공' })
  getMyProfile(@CurrentUser() user: AuthenticatedUser): Promise<UserResponseDto> {
    return this.userService.findById(user.id);
  }

  @Patch('me')
  @ApiOperation({ summary: '내 프로필 수정' })
  @ApiStandardResponse(UserResponseDto, { message: '내 프로필 수정 완료' })
  updateMyProfile(
    @CurrentUser() user: AuthenticatedUser,
    @Body() dto: UpdateUserDto,
  ): Promise<UserResponseDto> {
    return this.userService.update(user.id, dto);
  }
}
