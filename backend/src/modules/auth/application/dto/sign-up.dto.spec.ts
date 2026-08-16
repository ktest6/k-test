import { plainToInstance } from 'class-transformer';
import { validate } from 'class-validator';
import { IdentityDocumentType } from '../../../user/domain/enums/identity-document-type.enum';
import { SignUpDto } from './sign-up.dto';

function validPayload(): Record<string, unknown> {
  return {
    email: 'student@example.com',
    password: '12341234!!',
    firstName: 'GILDONG',
    lastName: 'HONG',
    nationality: 'KOR',
    birthDate: '1995-05-20',
    idType: IdentityDocumentType.PASSPORT,
    idNumber: 'M12345678',
    agreedToTerms: true,
    agreedToPrivacyPolicy: true,
    agreedToPassportProcessing: true,
  };
}

describe('SignUpDto', () => {
  it('passes validation with a fully valid payload', async () => {
    const dto = plainToInstance(SignUpDto, validPayload());
    const errors = await validate(dto);
    expect(errors).toHaveLength(0);
  });

  it('rejects registration when terms are not agreed to', async () => {
    const dto = plainToInstance(SignUpDto, { ...validPayload(), agreedToTerms: false });
    const errors = await validate(dto);
    expect(errors.some((e) => e.property === 'agreedToTerms')).toBe(true);
  });

  it('rejects registration when the privacy policy is not agreed to', async () => {
    const dto = plainToInstance(SignUpDto, { ...validPayload(), agreedToPrivacyPolicy: false });
    const errors = await validate(dto);
    expect(errors.some((e) => e.property === 'agreedToPrivacyPolicy')).toBe(true);
  });

  it('rejects registration when passport processing is not agreed to', async () => {
    const dto = plainToInstance(SignUpDto, {
      ...validPayload(),
      agreedToPassportProcessing: false,
    });
    const errors = await validate(dto);
    expect(errors.some((e) => e.property === 'agreedToPassportProcessing')).toBe(true);
  });

  it('rejects an unknown identity document type', async () => {
    const dto = plainToInstance(SignUpDto, { ...validPayload(), idType: 'DRIVER_LICENSE' });
    const errors = await validate(dto);
    expect(errors.some((e) => e.property === 'idType')).toBe(true);
  });

  it('allows registration without an optional company code', async () => {
    const payload = validPayload();
    delete payload.companyCode;
    const dto = plainToInstance(SignUpDto, payload);
    const errors = await validate(dto);
    expect(errors).toHaveLength(0);
  });

  it('allows registration with no identity document at all', async () => {
    const payload = validPayload();
    delete payload.idType;
    delete payload.idNumber;
    const dto = plainToInstance(SignUpDto, payload);
    const errors = await validate(dto);
    expect(errors).toHaveLength(0);
  });

  it('rejects an idType selected with no idNumber', async () => {
    const payload = validPayload();
    delete payload.idNumber;
    const dto = plainToInstance(SignUpDto, payload);
    const errors = await validate(dto);
    expect(errors.some((e) => e.property === 'idNumber')).toBe(true);
  });

  it('does not require idType when idNumber is present without it', async () => {
    const payload = validPayload();
    delete payload.idType;
    const dto = plainToInstance(SignUpDto, payload);
    const errors = await validate(dto);
    expect(errors).toHaveLength(0);
  });

  it('allows registration without the optional voice data AI training consent', async () => {
    const dto = plainToInstance(SignUpDto, validPayload());
    const errors = await validate(dto);
    expect(errors).toHaveLength(0);
  });

  it('rejects a non-boolean voice data AI training consent value', async () => {
    const dto = plainToInstance(SignUpDto, {
      ...validPayload(),
      agreedToVoiceDataAiTraining: 'yes',
    });
    const errors = await validate(dto);
    expect(errors.some((e) => e.property === 'agreedToVoiceDataAiTraining')).toBe(true);
  });
});
