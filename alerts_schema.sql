-- MediSmartAI: Inventory Alerts feature
-- Run this once against your medismart_db database, e.g.:
--   mysql -u root medismart_db < alerts_schema.sql

CREATE TABLE IF NOT EXISTS alert_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    admin_phone VARCHAR(20) NOT NULL,
    alert_time TIME NOT NULL DEFAULT '09:00:00',
    low_stock_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    expiry_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    expiry_days_threshold INT NOT NULL DEFAULT 30,
    last_alert_sent_date DATE NULL
);
