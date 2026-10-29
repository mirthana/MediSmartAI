-- MediSmartAI: Billing system
-- Run this once against your medismart_db database, e.g.:
--   python run_migration.py   (see run_billing_migration.py)
-- or import it via MySQL Workbench / phpMyAdmin.

CREATE TABLE IF NOT EXISTS bills (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_name VARCHAR(150) NOT NULL,
    customer_phone VARCHAR(20),
    bill_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_amount DECIMAL(10,2) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bill_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    bill_id INT NOT NULL,
    medicine_id INT NOT NULL,
    medicine_name VARCHAR(150) NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    subtotal DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (bill_id) REFERENCES bills(id) ON DELETE CASCADE
);

-- Created here defensively in case it doesn't already exist in your
-- database. The AI Prediction page already reads from this table.
CREATE TABLE IF NOT EXISTS medicine_sales (
    id INT AUTO_INCREMENT PRIMARY KEY,
    medicine_id INT NOT NULL,
    sale_date DATE NOT NULL,
    quantity_sold INT NOT NULL
);
