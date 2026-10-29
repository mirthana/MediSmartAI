-- MediSmartAI: Medicine Reminder upgrade
-- Adds Start Date / End Date to reminders, and a fixed-slot schedule
-- (Morning 08:00 / Afternoon 14:00 / Night 20:00) per reminder.
--
-- Run with:  python run_reminder_migration.py
-- (that script is safe to run more than once; running these
--  ALTER statements directly is NOT safe to repeat)

ALTER TABLE medicine_reminders ADD COLUMN start_date DATE NULL;
ALTER TABLE medicine_reminders ADD COLUMN end_date DATE NULL;

CREATE TABLE IF NOT EXISTS reminder_slots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    reminder_id INT NOT NULL,
    slot_name VARCHAR(20) NOT NULL,
    slot_time TIME NOT NULL,
    last_sent_date DATE NULL,
    FOREIGN KEY (reminder_id) REFERENCES medicine_reminders(id) ON DELETE CASCADE
);
