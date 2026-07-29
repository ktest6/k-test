import { Module } from '@nestjs/common';
import { USER_REPOSITORY } from './domain/user.repository.interface';
import { UserService } from './application/services/user.service';
import { SupabaseUserRepository } from './infrastructure/repositories/supabase-user.repository';
import { UserController } from './presentation/user.controller';

@Module({
  controllers: [UserController],
  providers: [UserService, { provide: USER_REPOSITORY, useClass: SupabaseUserRepository }],
  exports: [UserService],
})
export class UserModule {}
