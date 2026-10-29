"""
One-time migration script: creates the alert_settings table.
Run this once with:  python run_migration.py
"""

import mysql.connector

connection = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="medismart_db"
)

cursor = connection.cursor()

with open("alerts_schema.sql", "r") as f:
    sql_script = f.read()

# Split on ';' in case the file ever has more than one statement
for statement in sql_script.split(";"):
    statement = statement.strip()
    if statement:
        cursor.execute(statement)

connection.commit()
cursor.close()
connection.close()

print("Migration complete: alert_settings table is ready.")
