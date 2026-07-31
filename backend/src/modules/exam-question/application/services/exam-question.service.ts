import { Inject, Injectable } from '@nestjs/common';
import {
  ConflictDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { ExamService } from '../../../exam/application/services/exam.service';
import { Question } from '../../../question/domain/entities/question.entity';
import { QuestionService } from '../../../question/application/services/question.service';
import { ExamQuestion } from '../../domain/entities/exam-question.entity';
import {
  EXAM_QUESTION_REPOSITORY,
  ExamQuestionRepository,
} from '../../domain/exam-question.repository.interface';

@Injectable()
export class ExamQuestionService {
  constructor(
    @Inject(EXAM_QUESTION_REPOSITORY)
    private readonly examQuestionRepository: ExamQuestionRepository,
    private readonly examService: ExamService,
    private readonly questionService: QuestionService,
  ) {}

  async assign(examId: string, questionId: string, adminId: string): Promise<ExamQuestion> {
    await this.examService.findById(examId);
    await this.questionService.findById(questionId);

    const existing = await this.examQuestionRepository.findActiveByExamAndQuestion(
      examId,
      questionId,
    );
    if (existing) {
      throw new ConflictDomainException('이미 이 회차에 배정된 문항입니다.');
    }

    return this.examQuestionRepository.create({ examId, questionId, assignedBy: adminId });
  }

  async unassign(examId: string, questionId: string): Promise<void> {
    const existing = await this.examQuestionRepository.findActiveByExamAndQuestion(
      examId,
      questionId,
    );
    if (!existing) {
      throw new NotFoundDomainException('배정된 문항을 찾을 수 없습니다.');
    }
    await this.examQuestionRepository.unassign(existing.id);
  }

  async listAssignedQuestions(examId: string): Promise<Question[]> {
    await this.examService.findById(examId);
    const assignments = await this.examQuestionRepository.findActiveByExam(examId);
    return this.questionService.findByIds(assignments.map((a) => a.questionId));
  }
}
