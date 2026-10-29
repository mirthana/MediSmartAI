"""
One-time migration script: creates the billing tables
(bills, bill_items, medicine_sales).

Run this once with:  python run_billing_migration.py
"""

import mysql.connector

connection = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="medismart_db"
)

cursor = connection.cursor()

with open("billing_schema.sql", "r") as f:
    sql_script = f.read()

for statement in sql_script.split(";"):
    statement = statement.strip()
    if statement:
        cursor.execute(statement)

connection.commit()
cursor.close()
connection.close()

print("Migration complete: bills, bill_items, and medicine_sales tables are ready.")
