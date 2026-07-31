import { Module } from '@nestjs/common';
import { ADMIN_REPOSITORY } from './domain/admin.repository.interface';
import { AdminService } from './application/services/admin.service';
import { SupabaseAdminRepository } from './infrastructure/repositories/supabase-admin.repository';

@Module({
  providers: [AdminService, { provide: ADMIN_REPOSITORY, useClass: SupabaseAdminRepository }],
  exports: [AdminService],
})
export class AdminModule {}
