import { Inject, Injectable, Logger } from '@nestjs/common';
import * as bcrypt from 'bcrypt';
import {
  ConflictDomainException,
  NotFoundDomainException,
  UnauthorizedDomainException,
} from '../../../../common/exceptions/domain.exception';
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
      throw new ConflictDomainException('이미 사용 중인 이메일입니다.');
    }
    if (input.idType && input.idNumber) {
      const identityTaken = await this.userRepository.existsByIdentityDocument(
        input.idType,
        input.idNumber,
      );
      if (identityTaken) {
        throw new ConflictDomainException('이미 등록된 신분증 정보입니다.');
      }
    }

    const passwordHash = await bcrypt.hash(input.password, PASSWORD_SALT_ROUNDS);
    return this.userRepository.register({ ...input, passwordHash });
  }

  async verifyCredentials(email: string, password: string): Promise<User> {
    const credentials = await this.userRepository.findCredentialsByEmail(email);
    if (!credentials) {
      this.logger.warn(`로그인 실패 (계정 없음): email=${email}`);
      throw new UnauthorizedDomainException('이메일 또는 비밀번호가 올바르지 않습니다.');
    }

    const matches = await bcrypt.compare(password, credentials.passwordHash);
    if (!matches) {
      await this.userRepository.recordLoginFailure(credentials.user.id);
      this.logger.warn(`로그인 실패 (비밀번호 불일치): email=${email}`);
      throw new UnauthorizedDomainException('이메일 또는 비밀번호가 올바르지 않습니다.');
    }

    await this.userRepository.recordLoginSuccess(credentials.user.id);
    return credentials.user;
  }

  async findById(id: string): Promise<User> {
    const user = await this.userRepository.findById(id);
    if (!user) {
      throw new NotFoundDomainException(`사용자(${id})를 찾을 수 없습니다.`);
    }
    return user;
  }

  update(id: string, input: UpdateUserProfileInput): Promise<User> {
    return this.userRepository.update(id, input);
  }

  list(): Promise<User[]> {
    return this.userRepository.list();
  }
}
