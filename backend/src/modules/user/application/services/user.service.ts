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
import { User } from '../../domain/entities/user.entity';
import { IdentityDocumentType } from '../../domain/enums/identity-document-type.enum';
import {
  UpdateUserProfileInput,
  USER_REPOSITORY,
  UserRepository,
} from '../../domain/user.repository.interface';

const PASSWORD_SALT_ROUNDS = 10;

export interface RegisterUserRequest {
  email: string;
  password: string;
  firstName: string;
  lastName: string;
  nationality: string;
  birthDate: string;
  idType?: IdentityDocumentType;
  idNumber?: string;
  companyCode?: string;
  termsAgreedAt: Date;
  privacyAgreedAt: Date;
  passportProcessingAgreedAt: Date;
  emailVerifiedAt: Date;
  voiceDataAiTrainingAgreedAt: Date | null;
}

@Injectable()
export class UserService {
  private readonly logger = new Logger(UserService.name);

  constructor(@Inject(USER_REPOSITORY) private readonly userRepository: UserRepository) {}

  existsByEmail(email: string): Promise<boolean> {
    return this.userRepository.existsByEmail(email);
  }

  async register(input: RegisterUserRequest): Promise<User> {
    const emailTaken = await this.userRepository.existsByEmail(input.email);
    if (emailTaken) {
      throw new ConflictDomainException(EMAIL_ALREADY_IN_USE);
    }
    if (input.idType && input.idNumber) {
      const identityTaken = await this.userRepository.existsByIdentityDocument(
        input.idType,
        input.idNumber,
      );
      if (identityTaken) {
        throw new ConflictDomainException('This identity document is already registered.');
      }
    }

    const passwordHash = await bcrypt.hash(input.password, PASSWORD_SALT_ROUNDS);
    return this.userRepository.register({ ...input, passwordHash });
  }

  async verifyCredentials(email: string, password: string): Promise<User> {
    const credentials = await this.userRepository.findCredentialsByEmail(email);
    if (!credentials) {
      this.logger.warn(`로그인 실패 (계정 없음): email=${email}`);
      throw new UnauthorizedDomainException(INVALID_CREDENTIALS);
    }

    const matches = await bcrypt.compare(password, credentials.passwordHash);
    if (!matches) {
      await this.userRepository.recordLoginFailure(credentials.user.id);
      this.logger.warn(`로그인 실패 (비밀번호 불일치): email=${email}`);
      throw new UnauthorizedDomainException(INVALID_CREDENTIALS);
    }

    await this.userRepository.recordLoginSuccess(credentials.user.id);
    return credentials.user;
  }

  async findById(id: string): Promise<User> {
    const user = await this.userRepository.findById(id);
    if (!user) {
      throw new NotFoundDomainException(notFound('User', id));
    }
    return user;
  }

  findByEmail(email: string): Promise<User | null> {
    return this.userRepository.findByEmail(email);
  }

  update(id: string, input: UpdateUserProfileInput): Promise<User> {
    return this.userRepository.update(id, input);
  }

  list(): Promise<User[]> {
    return this.userRepository.list();
  }
}
