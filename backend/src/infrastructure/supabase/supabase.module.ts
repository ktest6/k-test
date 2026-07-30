import { Global, Module } from '@nestjs/common';
import { StorageUploadUrlService } from './storage-upload-url.service';
import { SupabaseService } from './supabase.service';

@Global()
@Module({
  providers: [SupabaseService, StorageUploadUrlService],
  exports: [SupabaseService, StorageUploadUrlService],
})
export class SupabaseModule {}
