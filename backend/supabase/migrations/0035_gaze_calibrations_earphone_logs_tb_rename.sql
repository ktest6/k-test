-- gaze_calibrations, earphone_logs를 다른 주 도메인 테이블(tb_user, tb_exam 등)과 같은
-- tb_ prefix + {table}_id(SERIAL) 네이밍으로 맞춘다. 두 테이블 다 이 PK를 참조하는
-- 다른 테이블이 없어 기존 행은 유지한 채 PK만 새로 채번해도 안전하다.

alter table gaze_calibrations rename to tb_gaze_calibrations;
alter table tb_gaze_calibrations drop constraint gaze_calibrations_pkey;
alter table tb_gaze_calibrations drop column id;
alter table tb_gaze_calibrations add column gaze_calibration_id serial primary key;
alter index idx_gaze_calibrations_exam_user rename to idx_tb_gaze_calibrations_exam_user;

alter table earphone_logs rename to tb_earphone_logs;
alter table tb_earphone_logs drop constraint earphone_logs_pkey;
alter table tb_earphone_logs drop column id;
alter table tb_earphone_logs add column earphone_log_id serial primary key;
alter index idx_earphone_logs_exam_user rename to idx_tb_earphone_logs_exam_user;
