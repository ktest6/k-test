import { Module } from '@nestjs/common';
import { AiModule } from '../ai/ai.module';
import { QuestionModule } from '../question/question.module';
import { DOCUMENT_REPOSITORY } from './domain/document.repository.interface';
import { DocumentUploadedListener } from './application/listeners/document-uploaded.listener';
import { DocumentService } from './application/services/document.service';
import { SupabaseDocumentRepository } from './infrastructure/repositories/supabase-document.repository';
import { DocumentController } from './presentation/document.controller';

@Module({
  imports: [AiModule, QuestionModule],
  controllers: [DocumentController],
  providers: [
    DocumentService,
    DocumentUploadedListener,
    { provide: DOCUMENT_REPOSITORY, useClass: SupabaseDocumentRepository },
  ],
  exports: [DocumentService],
})
export class DocumentModule {}
