import { ApiProperty } from '@nestjs/swagger';
import { Role } from '../../../../common/enums/role.enum';

export class MeResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  email: string;

  @ApiProperty({ enum: Role })
  role: Role;
}
