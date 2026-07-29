import { Module } from '@nestjs/common';
import { UserModule } from '../user/user.module';
import { AuthService } from './application/services/auth.service';
import { AuthController } from './presentation/auth.controller';

@Module({
  imports: [UserModule],
  controllers: [AuthController],
  providers: [AuthService],
})
export class AuthModule {}
