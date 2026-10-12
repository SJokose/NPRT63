"""
Adds the two stored procedures that were missing from migration 0009:
- sp_block_range (used by "Block whole day" / "Block range")
- sp_unblock_slot (used by the unblock button)
"""
from django.db import migrations


SP_BLOCK_RANGE = """
CREATE PROCEDURE sp_block_range(
    IN p_doctor_id  BIGINT,
    IN p_start_date DATE,
    IN p_end_date   DATE,
    IN p_start_time TIME,
    IN p_end_time   TIME,
    IN p_reason     VARCHAR(200)
)
BEGIN
    DECLARE v_cur_date DATE;
    DECLARE v_cur_time TIME;
    DECLARE v_end_time TIME;

    IF p_start_date > p_end_date THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Start date must be before end date.';
    END IF;

    IF p_start_date < CURDATE() THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Cannot block a slot in the past.';
    END IF;

    IF p_start_time IS NULL THEN SET v_cur_time = '09:00:00';
    ELSE SET v_cur_time = p_start_time; END IF;

    IF p_end_time IS NULL THEN SET v_end_time = '17:00:00';
    ELSE SET v_end_time = p_end_time; END IF;

    SET v_cur_date = p_start_date;

    day_loop: WHILE v_cur_date <= p_end_date DO
        SET v_cur_time = IF(p_start_time IS NULL, '09:00:00', p_start_time);

        time_loop: WHILE v_cur_time <= v_end_time DO
            INSERT IGNORE INTO blocked_slots
                (doctor_id, blocked_date, blocked_time, reason, created_at)
            VALUES
                (p_doctor_id, v_cur_date, v_cur_time, p_reason, NOW());

            SET v_cur_time = ADDTIME(v_cur_time, '00:30:00');
        END WHILE;

        SET v_cur_date = DATE_ADD(v_cur_date, INTERVAL 1 DAY);
    END WHILE;
END
"""


SP_UNBLOCK_SLOT = """
CREATE PROCEDURE sp_unblock_slot(
    IN p_doctor_id BIGINT,
    IN p_date      DATE,
    IN p_reason    VARCHAR(255)
)
BEGIN
    DELETE FROM blocked_slots
     WHERE doctor_id = p_doctor_id
       AND blocked_date = p_date
       AND reason = p_reason;
END
"""


PROCEDURES = {
    'sp_block_range': SP_BLOCK_RANGE,
    'sp_unblock_slot': SP_UNBLOCK_SLOT,
}


def install_procedures(apps, schema_editor):
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
        ('core', '0009_stored_procedures'),
    ]

    operations = [
        migrations.RunPython(install_procedures, remove_procedures),
    ]