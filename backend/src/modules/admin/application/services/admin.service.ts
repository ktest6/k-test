import { Inject, Injectable, Logger } from '@nestjs/common';
import * as bcrypt from 'bcrypt';
import {
  ConflictDomainException,
  NotFoundDomainException,
  UnauthorizedDomainException,
} from '../../../../common/exceptions/domain.exception';
import {
  EMAIL_ALREADY_IN_USE,
  INVALID_CREDENTIALS,
  notFound,
} from '../../../../common/exceptions/error-messages';
import { Admin } from '../../domain/entities/admin.entity';
import { ADMIN_REPOSITORY, AdminRepository } from '../../domain/admin.repository.interface';

const PASSWORD_SALT_ROUNDS = 10;

export interface RegisterAdminRequest {
  email: string;
  password: string;
  name: string;
}

@Injectable()
export class AdminService {
  private readonly logger = new Logger(AdminService.name);

  constructor(@Inject(ADMIN_REPOSITORY) private readonly adminRepository: AdminRepository) {}

  async register(input: RegisterAdminRequest): Promise<Admin> {
    const emailTaken = await this.adminRepository.existsByEmail(input.email);
    if (emailTaken) {
      throw new ConflictDomainException(EMAIL_ALREADY_IN_USE);
    }

    const passwordHash = await bcrypt.hash(input.password, PASSWORD_SALT_ROUNDS);
    return this.adminRepository.register({
      email: input.email,
      name: input.name,
      passwordHash,
    });
  }

  async verifyCredentials(email: string, password: string): Promise<Admin> {
    const credentials = await this.adminRepository.findCredentialsByEmail(email);
    if (!credentials) {
      this.logger.warn(`관리자 로그인 실패 (계정 없음): email=${email}`);
      throw new UnauthorizedDomainException(INVALID_CREDENTIALS);
    }

    const matches = await bcrypt.compare(password, credentials.passwordHash);
    if (!matches) {
      await this.adminRepository.recordLoginFailure(credentials.admin.id);
      this.logger.warn(`관리자 로그인 실패 (비밀번호 불일치): email=${email}`);
      throw new UnauthorizedDomainException(INVALID_CREDENTIALS);
    }

    await this.adminRepository.recordLoginSuccess(credentials.admin.id);
    return credentials.admin;
  }

  async findById(id: string): Promise<Admin> {
    const admin = await this.adminRepository.findById(id);
    if (!admin) {
      throw new NotFoundDomainException(notFound('Admin', id));
    }
    return admin;
  }
}
