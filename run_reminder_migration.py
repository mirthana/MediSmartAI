"""
One-time migration script for the Medicine Reminder upgrade.
Safe to run more than once - it skips anything that already exists.

Run this once with:  python run_reminder_migration.py
"""

import mysql.connector

connection = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="medismart_db"
)

cursor = connection.cursor()

# --------------------------------------
# Add start_date / end_date to medicine_reminders
# --------------------------------------

alter_statements = [
    "ALTER TABLE medicine_reminders ADD COLUMN start_date DATE NULL",
    "ALTER TABLE medicine_reminders ADD COLUMN end_date DATE NULL"
]

for statement in alter_statements:

    try:
        cursor.execute(statement)
        print("Added column.")

    except mysql.connector.Error as e:

        # 1060 = Duplicate column name (already migrated before)
        if e.errno == 1060:
            print("Column already exists, skipping.")
        else:
            raise

# --------------------------------------
# Create reminder_slots table
# --------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS reminder_slots (
        id INT AUTO_INCREMENT PRIMARY KEY,
        reminder_id INT NOT NULL,
        slot_name VARCHAR(20) NOT NULL,
        slot_time TIME NOT NULL,
        last_sent_date DATE NULL,
        FOREIGN KEY (reminder_id) REFERENCES medicine_reminders(id) ON DELETE CASCADE
    )
    """
)

connection.commit()
cursor.close()
connection.close()

print("Migration complete: start_date, end_date, and reminder_slots are ready.")
