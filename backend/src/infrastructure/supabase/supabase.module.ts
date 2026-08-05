import { Global, Module } from '@nestjs/common';
import { StoragePublicUrlService } from './storage-public-url.service';
import { StorageUploadUrlService } from './storage-upload-url.service';
import { SupabaseService } from './supabase.service';

@Global()
@Module({
  providers: [SupabaseService, StorageUploadUrlService, StoragePublicUrlService],
  exports: [SupabaseService, StorageUploadUrlService, StoragePublicUrlService],
})
export class SupabaseModule {}
