"""
Migration that installs the MySQL stored procedures used by MediSync.

Django creates a fresh `test_mediasyncc` database when running tests, and
manual procedures created in Workbench are NOT copied over. This migration
makes sure they exist in every database Django builds.
"""
from django.db import migrations


SP_BOOK_APPOINTMENT = """
CREATE PROCEDURE sp_book_appointment(
    IN p_doctor_id   BIGINT,
    IN p_patient_id  BIGINT,
    IN p_date        DATE,
    IN p_time        TIME,
    IN p_duration    INT,
    IN p_reason      TEXT,
    OUT p_new_id     BIGINT
)
BEGIN
    DECLARE v_doctor_role  VARCHAR(20);
    DECLARE v_patient_role VARCHAR(20);
    DECLARE v_conflict     INT DEFAULT 0;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT role INTO v_doctor_role  FROM core_user WHERE id = p_doctor_id;
    SELECT role INTO v_patient_role FROM core_user WHERE id = p_patient_id;

    IF v_doctor_role IS NULL OR v_doctor_role <> 'doctor' THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Selected user is not a doctor.';
    END IF;

    IF v_patient_role IS NULL OR v_patient_role <> 'patient' THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Selected user is not a patient.';
    END IF;

    IF TIMESTAMP(p_date, p_time) <= NOW() THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Cannot book an appointment in the past.';
    END IF;

    SELECT COUNT(*) INTO v_conflict
      FROM core_appointment
     WHERE patient_id = p_patient_id
       AND appointment_date = p_date
       AND status IN ('pending','confirmed');
    IF v_conflict > 0 THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'You already have an appointment on this day.';
    END IF;

    SELECT COUNT(*) INTO v_conflict
      FROM core_appointment
     WHERE doctor_id = p_doctor_id
       AND appointment_date = p_date
       AND appointment_time = p_time
       AND status IN ('pending','confirmed');
    IF v_conflict > 0 THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This doctor is already booked for that time slot.';
    END IF;

    SELECT COUNT(*) INTO v_conflict
      FROM blocked_slots
     WHERE doctor_id = p_doctor_id
       AND blocked_date = p_date
       AND blocked_time = p_time;
    IF v_conflict > 0 THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This slot is blocked by the doctor.';
    END IF;

    INSERT INTO core_appointment
        (patient_id, doctor_id, appointment_date, appointment_time,
         duration_minutes, reason_for_visit, status,
         reminder_sent_72h, reminder_sent_24h, reminder_sent_2h,
         rescheduled_count, created_at, updated_at)
    VALUES
        (p_patient_id, p_doctor_id, p_date, p_time,
         IFNULL(p_duration,30), IFNULL(p_reason,''), 'pending',
         0,0,0,
         0, NOW(), NOW());

    SET p_new_id = LAST_INSERT_ID();
    COMMIT;
END
"""


SP_CANCEL_APPOINTMENT = """
CREATE PROCEDURE sp_cancel_appointment(
    IN p_appointment_id BIGINT,
    IN p_reason         TEXT
)
BEGIN
    DECLARE v_status VARCHAR(20);

    START TRANSACTION;

    SELECT status INTO v_status
      FROM core_appointment
     WHERE id = p_appointment_id
     FOR UPDATE;

    IF v_status IS NULL THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Appointment not found.';
    END IF;

    IF v_status IN ('cancelled','completed','missed') THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This appointment cannot be cancelled.';
    END IF;

    UPDATE core_appointment
       SET status = 'cancelled',
           cancelled_at = NOW(),
           cancellation_reason = IFNULL(p_reason, ''),
           updated_at = NOW()
     WHERE id = p_appointment_id;

    UPDATE core_followup
       SET status = 'due',
           scheduled_appointment_id = NULL,
           updated_at = NOW()
     WHERE scheduled_appointment_id = p_appointment_id
       AND status = 'scheduled';

    COMMIT;
END
"""


SP_RESCHEDULE_APPOINTMENT = """
CREATE PROCEDURE sp_reschedule_appointment(
    IN  p_appointment_id BIGINT,
    IN  p_new_date       DATE,
    IN  p_new_time       TIME,
    IN  p_new_reason     TEXT,
    OUT p_new_appt_id    BIGINT
)
BEGIN
    DECLARE v_doctor_id   BIGINT;
    DECLARE v_patient_id  BIGINT;
    DECLARE v_old_status  VARCHAR(20);
    DECLARE v_conflict    INT DEFAULT 0;
    DECLARE v_doctor_role VARCHAR(20);
    DECLARE v_patient_role VARCHAR(20);

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT doctor_id, patient_id, status
      INTO v_doctor_id, v_patient_id, v_old_status
      FROM core_appointment
     WHERE id = p_appointment_id
     FOR UPDATE;

    IF v_doctor_id IS NULL THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Appointment not found.';
    END IF;

    IF v_old_status NOT IN ('pending','confirmed') THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This appointment cannot be rescheduled.';
    END IF;

    IF TIMESTAMP(p_new_date, p_new_time) <= NOW() THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Cannot reschedule to a slot in the past.';
    END IF;

    SELECT role INTO v_doctor_role  FROM core_user WHERE id = v_doctor_id;
    SELECT role INTO v_patient_role FROM core_user WHERE id = v_patient_id;

    IF v_doctor_role IS NULL OR v_doctor_role <> 'doctor' THEN
        ROLLBACK; SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Doctor not valid.';
    END IF;
    IF v_patient_role IS NULL OR v_patient_role <> 'patient' THEN
        ROLLBACK; SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patient not valid.';
    END IF;

    SELECT COUNT(*) INTO v_conflict
      FROM core_appointment
     WHERE patient_id = v_patient_id
       AND appointment_date = p_new_date
       AND status IN ('pending','confirmed')
       AND id <> p_appointment_id;
    IF v_conflict > 0 THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'You already have an appointment on this day.';
    END IF;

    SELECT COUNT(*) INTO v_conflict
      FROM core_appointment
     WHERE doctor_id = v_doctor_id
       AND appointment_date = p_new_date
       AND appointment_time = p_new_time
       AND status IN ('pending','confirmed')
       AND id <> p_appointment_id;
    IF v_conflict > 0 THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This doctor is already booked for that time slot.';
    END IF;

    SELECT COUNT(*) INTO v_conflict
      FROM blocked_slots
     WHERE doctor_id = v_doctor_id
       AND blocked_date = p_new_date
       AND blocked_time = p_new_time;
    IF v_conflict > 0 THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This slot is blocked by the doctor.';
    END IF;

    UPDATE core_appointment
       SET status = 'cancelled',
           cancelled_at = NOW(),
           cancellation_reason = 'Rescheduled'
     WHERE id = p_appointment_id;

    INSERT INTO core_appointment
        (patient_id, doctor_id, appointment_date, appointment_time,
         duration_minutes, reason_for_visit, status,
         reminder_sent_72h, reminder_sent_24h, reminder_sent_2h,
         rescheduled_count, last_rescheduled_at, created_at, updated_at)
    VALUES
        (v_patient_id, v_doctor_id, p_new_date, p_new_time,
         30, IFNULL(p_new_reason,''), 'pending',
         0,0,0,
         1, NOW(), NOW(), NOW());

    SET p_new_appt_id = LAST_INSERT_ID();
    COMMIT;
END
"""


SP_BLOCK_SLOT = """
CREATE PROCEDURE sp_block_slot(
    IN p_doctor_id BIGINT,
    IN p_date      DATE,
    IN p_time      TIME,
    IN p_reason    VARCHAR(255)
)
BEGIN
    DECLARE v_conflict INT DEFAULT 0;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT COUNT(*) INTO v_conflict
      FROM core_appointment
     WHERE doctor_id = p_doctor_id
       AND appointment_date = p_date
       AND appointment_time = p_time
       AND status IN ('pending','confirmed')
     FOR UPDATE;

    IF v_conflict > 0 THEN
        ROLLBACK;
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Cannot block this slot - a patient is already booked.';
    END IF;

    INSERT IGNORE INTO blocked_slots (doctor_id, blocked_date, blocked_time, reason, created_at)
    VALUES (p_doctor_id, p_date, p_time, IFNULL(p_reason,''), NOW());

    COMMIT;
END
"""


PROCEDURES = {
    'sp_book_appointment': SP_BOOK_APPOINTMENT,
    'sp_cancel_appointment': SP_CANCEL_APPOINTMENT,
    'sp_reschedule_appointment': SP_RESCHEDULE_APPOINTMENT,
    'sp_block_slot': SP_BLOCK_SLOT,
}


def install_procedures(apps, schema_editor):
    """Create each stored procedure. Ignore if it already exists."""
    from django.db import connection

    if connection.vendor != 'mysql':
        return

    with connection.cursor() as cursor:
        for name, body in PROCEDURES.items():
            cursor.execute(f"DROP PROCEDURE IF EXISTS {name}")
            cursor.execute(body)


def remove_procedures(apps, schema_editor):
    from django.db import connection

    if connection.vendor != 'mysql':
        return

    with connection.cursor() as cursor:
        for name in PROCEDURES:
            cursor.execute(f"DROP PROCEDURE IF EXISTS {name}")


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_blockedslot'),
    ]

    operations = [
        migrations.RunPython(install_procedures, remove_procedures),
    ]