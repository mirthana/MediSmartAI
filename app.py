

from flask import Flask, jsonify, render_template, request, redirect, url_for, session
import os
from dotenv import load_dotenv
from twilio.rest import Client
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import mysql.connector
from datetime import date, timedelta

# Fixed reminder time slots for the Start/End Date reminder upgrade
REMINDER_SLOT_TIMES = {
    "Morning": "08:00",
    "Afternoon": "14:00",
    "Night": "20:00"
}


# ==========================================
# LOAD ENVIRONMENT VARIABLES
# ==========================================

load_dotenv()


# ==========================================
# FLASK APPLICATION
# ==========================================

app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "medismart_secret_key_123"
)


# ==========================================
# TWILIO CONFIGURATION
# ==========================================

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")


twilio_client = Client(
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN
)
# ==========================================
# AUTOMATIC MEDICINE SMS REMINDER
# ==========================================

def check_medicine_reminders():

    print("CHECKING MEDICINE REMINDERS:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    now = datetime.now()
    current_time = now.strftime("%H:%M")
    today = now.date()

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # ==========================================
    # NEW: SLOT-BASED REMINDERS
    # (Start Date -> End Date, Morning/Afternoon/Night)
    # ==========================================

    cursor.execute("""
        SELECT
            reminder_slots.id AS slot_id,
            reminder_slots.slot_name,
            reminder_slots.slot_time,
            reminder_slots.last_sent_date,
            medicine_reminders.id AS reminder_id,
            medicine_reminders.patient_name,
            medicine_reminders.medicine_name,
            medicine_reminders.phone_number,
            medicine_reminders.notification_type,
            medicine_reminders.start_date,
            medicine_reminders.end_date
        FROM reminder_slots
        JOIN medicine_reminders
            ON reminder_slots.reminder_id = medicine_reminders.id
        WHERE medicine_reminders.notification_type = 'SMS'
    """)

    slot_reminders = cursor.fetchall()

    for row in slot_reminders:

        slot_time = str(row["slot_time"])[:5]

        if slot_time != current_time:
            continue

        # Not started yet
        if row["start_date"] and today < row["start_date"]:
            continue

        # AUTOMATIC STOP: past the end date
        if row["end_date"] and today > row["end_date"]:
            continue

        # Already sent this exact slot today
        if row["last_sent_date"] == today:
            continue

        phone_number = str(row["phone_number"])

        if not phone_number.startswith("+"):
            phone_number = "+91" + phone_number

        try:

            message = twilio_client.messages.create(

                body="sms_appointment_reminders",

                from_=TWILIO_PHONE_NUMBER,

                to=phone_number
            )

            print("================================")
            print("MEDICINE REMINDER SMS SENT (" + row["slot_name"] + ")")
            print("Patient:", row["patient_name"])
            print("Medicine:", row["medicine_name"])
            print("Message SID:", message.sid)
            print("================================")

            cursor.execute(
                """
                UPDATE reminder_slots
                SET last_sent_date = %s
                WHERE id = %s
                """,
                (today, row["slot_id"])
            )

        except Exception as e:

            print("SMS ERROR:", e)

    connection.commit()

    # ==========================================
    # LEGACY: OLD-STYLE SINGLE-TIME REMINDERS
    # (reminders created before this upgrade, with no slots)
    # ==========================================

    cursor.execute("""
        SELECT medicine_reminders.*
        FROM medicine_reminders
        LEFT JOIN reminder_slots
            ON reminder_slots.reminder_id = medicine_reminders.id
        WHERE medicine_reminders.notification_type = 'SMS'
        AND reminder_slots.id IS NULL
    """)

    reminders = cursor.fetchall()

    for reminder in reminders:

        reminder_time = str(reminder["reminder_time"])[:5]

        if reminder_time != current_time:
            continue

        frequency = reminder["frequency"]
        last_sent = reminder["last_sent"]

        # Prevent duplicate SMS
        if last_sent is not None:

            last_sent_date = last_sent.date()

            if frequency == "Daily" and last_sent_date == now.date():
                continue

            if frequency == "Weekly":
                days_passed = (now.date() - last_sent_date).days

                if days_passed < 7:
                    continue

            if frequency == "Once":
                continue

        # Convert Indian 10-digit number to international format
        phone_number = str(reminder["phone_number"])

        if not phone_number.startswith("+"):
            phone_number = "+91" + phone_number

        try:

            # Twilio Trial predefined template
            message = twilio_client.messages.create(

                body="sms_appointment_reminders",

                from_=TWILIO_PHONE_NUMBER,

                to=phone_number
            )

            print("================================")
            print("MEDICINE REMINDER SMS SENT")
            print("Patient:", reminder["patient_name"])
            print("Medicine:", reminder["medicine_name"])
            print("Message SID:", message.sid)
            print("================================")

            # Update sent time
            cursor.execute("""
                UPDATE medicine_reminders
                SET last_sent = %s
                WHERE id = %s
            """, (now, reminder["id"]))

            # Once reminders are marked as completed
            if frequency == "Once":

                cursor.execute("""
                    UPDATE medicine_reminders
                    SET sent = TRUE
                    WHERE id = %s
                """, (reminder["id"],))

        except Exception as e:

            print("SMS ERROR:", e)

    connection.commit()

    cursor.close()
    connection.close()


# ==========================================
# AUTOMATIC LOW STOCK / EXPIRY ALERTS
# ==========================================

def check_inventory_alerts():

    print("CHECKING INVENTORY ALERTS:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    now = datetime.now()
    current_time = now.strftime("%H:%M")
    today = now.date()

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("SELECT * FROM alert_settings LIMIT 1")
    settings = cursor.fetchone()

    # No settings configured yet
    if not settings or not settings["admin_phone"]:

        cursor.close()
        connection.close()
        return

    alert_time = str(settings["alert_time"])[:5]

    # Only run at the configured time
    if alert_time != current_time:

        cursor.close()
        connection.close()
        return

    # Already sent an alert today
    if settings["last_alert_sent_date"] == today:

        cursor.close()
        connection.close()
        return

    cursor.execute("SELECT * FROM medicines")
    medicines = cursor.fetchall()

    low_stock_items = []
    expiring_items = []

    expiry_horizon = today + timedelta(
        days=settings["expiry_days_threshold"]
    )

    for medicine in medicines:

        if settings["low_stock_enabled"] and medicine["quantity"] <= medicine["minimum_stock"]:

            low_stock_items.append(medicine["name"])

        if settings["expiry_enabled"] and today <= medicine["expiry_date"] <= expiry_horizon:

            expiring_items.append(medicine["name"])

    # Nothing to report today
    if not low_stock_items and not expiring_items:

        cursor.close()
        connection.close()
        return

    message_parts = ["MediSmartAI Inventory Alert:"]

    if low_stock_items:

        message_parts.append(
            "Low stock (" + str(len(low_stock_items)) + "): " + ", ".join(low_stock_items)
        )

    if expiring_items:

        message_parts.append(
            "Expiring soon (" + str(len(expiring_items)) + "): " + ", ".join(expiring_items)
        )

    alert_message = " | ".join(message_parts)

    admin_phone = str(settings["admin_phone"])

    if not admin_phone.startswith("+"):
        admin_phone = "+91" + admin_phone

    try:

        message = twilio_client.messages.create(

            body=alert_message,

            from_=TWILIO_PHONE_NUMBER,

            to=admin_phone
        )

        print("================================")
        print("INVENTORY ALERT SMS SENT")
        print("To:", admin_phone)
        print("Low stock items:", low_stock_items)
        print("Expiring items:", expiring_items)
        print("Message SID:", message.sid)
        print("================================")

        cursor.execute(
            """
            UPDATE alert_settings
            SET last_alert_sent_date = %s
            WHERE id = %s
            """,
            (today, settings["id"])
        )

        connection.commit()

    except Exception as e:

        print("INVENTORY ALERT SMS ERROR:", e)

    cursor.close()
    connection.close()


# ==========================================
# DATABASE CONNECTION
# ==========================================

def get_db_connection():

    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="medismart_db"
    )


# ==========================================
# HOME
# ==========================================

@app.route("/")
def home():

    return render_template("index.html")


# ==========================================
# LOGIN
# ==========================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        if username == "admin" and password == "admin123":

            session["admin"] = True

            return redirect(url_for("dashboard"))

        return render_template(
            "login.html",
            error="Invalid username or password"
        )

    return render_template("login.html")


# ==========================================
# DASHBOARD
# ==========================================

@app.route("/dashboard")
def dashboard():

    if "admin" not in session:

        return redirect(url_for("login"))

    connection = get_db_connection()

    cursor = connection.cursor(dictionary=True)


    # --------------------------------------
    # GET MEDICINES
    # --------------------------------------

    cursor.execute(
        "SELECT * FROM medicines"
    )

    medicines = cursor.fetchall()

    total_medicines = len(medicines)


    # --------------------------------------
    # LOW STOCK
    # --------------------------------------

    low_stock = 0

    for medicine in medicines:

        if medicine["quantity"] <= medicine["minimum_stock"]:

            low_stock += 1


    # --------------------------------------
    # EXPIRING MEDICINES
    # --------------------------------------

    today = date.today()

    thirty_days = today + timedelta(days=30)

    expiring = 0

    for medicine in medicines:

        if today <= medicine["expiry_date"] <= thirty_days:

            expiring += 1


    # --------------------------------------
    # INVENTORY VALUE
    # --------------------------------------

    inventory_value = 0

    for medicine in medicines:

        inventory_value += (
            medicine["quantity"]
            * float(medicine["price"])
        )


    # --------------------------------------
    # GET REMINDERS (with time slots + status)
    # --------------------------------------

    cursor.execute(
        """
        SELECT
            medicine_reminders.*,
            GROUP_CONCAT(
                reminder_slots.slot_name
                ORDER BY reminder_slots.slot_time
                SEPARATOR ', '
            ) AS slots
        FROM medicine_reminders
        LEFT JOIN reminder_slots
            ON reminder_slots.reminder_id = medicine_reminders.id
        GROUP BY medicine_reminders.id
        ORDER BY medicine_reminders.id DESC
        """
    )

    reminders = cursor.fetchall()

    for reminder_row in reminders:

        if reminder_row["end_date"] and today > reminder_row["end_date"]:
            reminder_row["status"] = "Completed"

        elif reminder_row["start_date"] and today < reminder_row["start_date"]:
            reminder_row["status"] = "Upcoming"

        else:
            reminder_row["status"] = "Active"


    # --------------------------------------
    # CLOSE DATABASE
    # --------------------------------------

    cursor.close()

    connection.close()


    # --------------------------------------
    # SEND DATA TO DASHBOARD
    # --------------------------------------

    return render_template(
        "dashboard.html",

        medicines=medicines,

        total_medicines=total_medicines,

        low_stock=low_stock,

        expiring=expiring,

        inventory_value=round(
            inventory_value,
            2
        ),

        today=today,

        thirty_days=thirty_days,

        reminders=reminders,

        slot_times=REMINDER_SLOT_TIMES
    )


# ==========================================
# MEDICINES
# ==========================================

@app.route("/medicines")
def medicines():

    if "admin" not in session:

        return redirect(url_for("login"))

    connection = get_db_connection()

    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM medicines"
    )

    medicines = cursor.fetchall()

    cursor.close()

    connection.close()

    return render_template(
        "medicines.html",
        medicines=medicines
    )


# ==========================================
# ADD MEDICINE
# ==========================================

@app.route("/add_medicine", methods=["POST"])
def add_medicine():

    if "admin" not in session:

        return redirect(url_for("login"))

    name = request.form["name"]

    category = request.form["category"]

    quantity = int(
        request.form["quantity"]
    )

    minimum_stock = int(
        request.form["minimum_stock"]
    )

    expiry_date = request.form["expiry_date"]

    price = float(
        request.form["price"]
    )


    connection = get_db_connection()

    cursor = connection.cursor()


    cursor.execute(
        """
        INSERT INTO medicines
        (
            name,
            category,
            quantity,
            minimum_stock,
            expiry_date,
            price
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """,

        (
            name,
            category,
            quantity,
            minimum_stock,
            expiry_date,
            price
        )
    )


    connection.commit()

    cursor.close()

    connection.close()


    return redirect(
        url_for("medicines")
    )


# ==========================================
# EDIT MEDICINE
# ==========================================

@app.route(
    "/edit_medicine/<int:medicine_id>",
    methods=["GET", "POST"]
)
def edit_medicine(medicine_id):

    if "admin" not in session:

        return redirect(url_for("login"))


    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )


    if request.method == "POST":

        name = request.form["name"]

        category = request.form["category"]

        quantity = int(
            request.form["quantity"]
        )

        minimum_stock = int(
            request.form["minimum_stock"]
        )

        expiry_date = request.form["expiry_date"]

        price = float(
            request.form["price"]
        )


        cursor.execute(
            """
            UPDATE medicines

            SET
                name=%s,
                category=%s,
                quantity=%s,
                minimum_stock=%s,
                expiry_date=%s,
                price=%s

            WHERE id=%s
            """,

            (
                name,
                category,
                quantity,
                minimum_stock,
                expiry_date,
                price,
                medicine_id
            )
        )


        connection.commit()

        cursor.close()

        connection.close()


        return redirect(
            url_for("medicines")
        )


    cursor.execute(
        """
        SELECT *
        FROM medicines
        WHERE id=%s
        """,

        (medicine_id,)
    )

    medicine = cursor.fetchone()


    cursor.close()

    connection.close()


    return render_template(
        "edit_medicine.html",
        medicine=medicine
    )


# ==========================================
# DELETE MEDICINE
# ==========================================

@app.route(
    "/delete_medicine/<int:medicine_id>",
    methods=["POST"]
)
def delete_medicine(medicine_id):

    if "admin" not in session:

        return redirect(url_for("login"))


    connection = get_db_connection()

    cursor = connection.cursor()


    cursor.execute(
        """
        DELETE FROM medicines
        WHERE id=%s
        """,

        (medicine_id,)
    )


    connection.commit()

    cursor.close()

    connection.close()


    return redirect(
        url_for("medicines")
    )


# ==========================================
# AI DEMAND PREDICTION
# ==========================================

@app.route("/prediction")
def prediction():

    if "admin" not in session:

        return redirect(url_for("login"))


    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )


    cursor.execute(
        "SELECT * FROM medicines"
    )

    medicines = cursor.fetchall()


    predictions = []

    chart_data = []


    # --------------------------------------
    # PROCESS EACH MEDICINE
    # --------------------------------------

    for medicine in medicines:

        medicine_id = medicine["id"]

        current_stock = medicine["quantity"]


        # ----------------------------------
        # SALES HISTORY
        # ----------------------------------

        cursor.execute(
            """
            SELECT
                sale_date,
                quantity_sold

            FROM medicine_sales

            WHERE medicine_id=%s

            ORDER BY sale_date
            """,

            (medicine_id,)
        )

        sales = cursor.fetchall()


        # ----------------------------------
        # NOT ENOUGH DATA
        # ----------------------------------

        if len(sales) < 3:

            predicted_quantity = 0

            order_quantity = 0

            demand = "Not enough data"

            recommendation = (
                "Add at least 3 sales records"
            )

            insight = (
                f"More sales data is required for "
                f"{medicine['name']} to generate a "
                f"reliable AI prediction."
            )


            predictions.append({

                "name": medicine["name"],

                "current_stock": current_stock,

                "predicted_quantity":
                    predicted_quantity,

                "order_quantity":
                    order_quantity,

                "demand_level":
                    demand,

                "recommendation":
                    recommendation,

                "insight":
                    insight
            })


            chart_data.append({

                "name": medicine["name"],

                "current_stock":
                    current_stock,

                "predicted_quantity":
                    predicted_quantity
            })


            continue


        # ----------------------------------
        # TOTAL SALES
        # ----------------------------------

        total_sales = sum(

            int(sale["quantity_sold"])

            for sale in sales
        )


        number_of_sales_records = len(
            sales
        )


        average_daily_sales = (

            total_sales
            /
            number_of_sales_records
        )


        # ----------------------------------
        # 30 DAY PREDICTION
        # ----------------------------------

        predicted_quantity = round(

            average_daily_sales
            * 30
        )


        predicted_quantity = max(
            0,
            predicted_quantity
        )


        # ----------------------------------
        # ORDER QUANTITY
        # ----------------------------------

        order_quantity = max(

            0,

            predicted_quantity
            - current_stock
        )


        # ----------------------------------
        # DEMAND LEVEL
        # ----------------------------------

        if predicted_quantity > current_stock * 1.5:

            demand = "High"

            recommendation = (

                "Order approximately "
                + str(order_quantity)
                + " units"
            )


        elif predicted_quantity > current_stock:

            demand = "Medium"

            recommendation = (
                "Consider ordering stock soon"
            )


        else:

            demand = "Low"

            recommendation = (
                "Stock level is sufficient"
            )


        # ----------------------------------
        # AI INSIGHT
        # ----------------------------------

        if demand == "High":

            insight = (

                f"{medicine['name']} has high "
                f"predicted demand for the next "
                f"30 days. Current stock may not "
                f"be sufficient. Additional stock "
                f"should be ordered."
            )


        elif demand == "Medium":

            insight = (

                f"{medicine['name']} has moderate "
                f"predicted demand for the next "
                f"30 days. Consider increasing "
                f"stock to avoid a possible shortage."
            )


        else:

            insight = (

                f"{medicine['name']} has low "
                f"predicted demand for the next "
                f"30 days. Current stock appears "
                f"sufficient."
            )


        # ----------------------------------
        # SAVE PREDICTION
        # ----------------------------------

        predictions.append({

            "name": medicine["name"],

            "current_stock":
                current_stock,

            "predicted_quantity":
                predicted_quantity,

            "order_quantity":
                order_quantity,

            "demand_level":
                demand,

            "recommendation":
                recommendation,

            "insight":
                insight
        })


        # ----------------------------------
        # CHART DATA
        # ----------------------------------

        chart_data.append({

            "name": medicine["name"],

            "current_stock":
                current_stock,

            "predicted_quantity":
                predicted_quantity
        })


    cursor.close()

    connection.close()


    return render_template(

        "prediction.html",

        predictions=predictions,

        chart_data=chart_data
    )


# ==========================================
# MEDICINE REMINDER
# ==========================================

@app.route(
    "/reminder",
    methods=["GET", "POST"]
)
def reminder():

    if "admin" not in session:

        return redirect(
            url_for("login")
        )


    # --------------------------------------
    # SAVE REMINDER
    # --------------------------------------

    if request.method == "POST":

        patient_name = request.form[
            "patient_name"
        ]

        medicine_name = request.form[
            "medicine_name"
        ]

        phone_number = request.form[
            "phone_number"
        ]

        start_date = request.form[
            "start_date"
        ]

        end_date = request.form[
            "end_date"
        ]

        selected_slots = request.form.getlist(
            "slots[]"
        )

        notification_type = request.form[
            "notification_type"
        ]


        connection = get_db_connection()

        cursor = connection.cursor()


        if not selected_slots:

            cursor.close()

            connection.close()

            return render_template(
                "reminder.html",
                reminders=get_reminders_with_status(),
                error="Please select at least one time slot (Morning / Afternoon / Night).",
                slot_times=REMINDER_SLOT_TIMES
            )


        # First selected slot's time is stored on the main row too,
        # purely so older parts of the app that read reminder_time
        # still have something sensible to show.
        first_slot_time = REMINDER_SLOT_TIMES[selected_slots[0]]


        cursor.execute(
            """
            INSERT INTO medicine_reminders
            (
                patient_name,
                medicine_name,
                phone_number,
                reminder_time,
                frequency,
                notification_type,
                start_date,
                end_date
            )

            VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s)
            """,

            (
                patient_name,
                medicine_name,
                phone_number,
                first_slot_time,
                "Daily",
                notification_type,
                start_date,
                end_date
            )
        )

        reminder_id = cursor.lastrowid


        for slot_name in selected_slots:

            cursor.execute(
                """
                INSERT INTO reminder_slots
                (reminder_id, slot_name, slot_time)
                VALUES (%s, %s, %s)
                """,
                (
                    reminder_id,
                    slot_name,
                    REMINDER_SLOT_TIMES[slot_name]
                )
            )


        connection.commit()

        cursor.close()

        connection.close()


        return redirect(
            url_for("dashboard")
        )


    # --------------------------------------
    # GET REMINDERS
    # --------------------------------------

    return render_template(
        "reminder.html",
        reminders=get_reminders_with_status(),
        slot_times=REMINDER_SLOT_TIMES
    )


def get_reminders_with_status():

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )

    cursor.execute(
        """
        SELECT
            medicine_reminders.*,
            GROUP_CONCAT(
                reminder_slots.slot_name
                ORDER BY reminder_slots.slot_time
                SEPARATOR ', '
            ) AS slots
        FROM medicine_reminders
        LEFT JOIN reminder_slots
            ON reminder_slots.reminder_id = medicine_reminders.id
        GROUP BY medicine_reminders.id
        ORDER BY medicine_reminders.id DESC
        """
    )

    reminders = cursor.fetchall()

    cursor.close()

    connection.close()


    today = date.today()

    for reminder_row in reminders:

        if reminder_row["end_date"] and today > reminder_row["end_date"]:
            reminder_row["status"] = "Completed"

        elif reminder_row["start_date"] and today < reminder_row["start_date"]:
            reminder_row["status"] = "Upcoming"

        else:
            reminder_row["status"] = "Active"

    return reminders


# ==========================================
# TWILIO TRIAL SMS TEST
# ==========================================

@app.route("/test_sms")
def test_sms():

    # Your verified phone number
    target_phone = "+916383381300"

    try:

        message = twilio_client.messages.create(

            body="sms_appointment_reminders",

            from_=TWILIO_PHONE_NUMBER,

            to=target_phone
        )

        return jsonify({
            "status": "SMS Sent Successfully! 🚀",
            "message_sid": message.sid
        }), 200

    except Exception as e:

        return jsonify({
            "status": "SMS Failed ❌",
            "error": str(e)
        }), 500


# ==========================================
# INVENTORY ALERT SETTINGS
# ==========================================

@app.route(
    "/alert_settings",
    methods=["GET", "POST"]
)
def alert_settings():

    if "admin" not in session:

        return redirect(url_for("login"))


    connection = get_db_connection()

    cursor = connection.cursor(dictionary=True)


    # --------------------------------------
    # SAVE SETTINGS
    # --------------------------------------

    if request.method == "POST":

        admin_phone = request.form["admin_phone"]

        alert_time = request.form["alert_time"]

        low_stock_enabled = 1 if request.form.get("low_stock_enabled") == "on" else 0

        expiry_enabled = 1 if request.form.get("expiry_enabled") == "on" else 0

        expiry_days_threshold = int(
            request.form["expiry_days_threshold"]
        )


        cursor.execute(
            "SELECT id FROM alert_settings LIMIT 1"
        )

        existing = cursor.fetchone()


        if existing:

            cursor.execute(
                """
                UPDATE alert_settings
                SET
                    admin_phone=%s,
                    alert_time=%s,
                    low_stock_enabled=%s,
                    expiry_enabled=%s,
                    expiry_days_threshold=%s
                WHERE id=%s
                """,
                (
                    admin_phone,
                    alert_time,
                    low_stock_enabled,
                    expiry_enabled,
                    expiry_days_threshold,
                    existing["id"]
                )
            )

        else:

            cursor.execute(
                """
                INSERT INTO alert_settings
                (
                    admin_phone,
                    alert_time,
                    low_stock_enabled,
                    expiry_enabled,
                    expiry_days_threshold
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    admin_phone,
                    alert_time,
                    low_stock_enabled,
                    expiry_enabled,
                    expiry_days_threshold
                )
            )


        connection.commit()

        cursor.close()

        connection.close()

        return redirect(
            url_for("alert_settings")
        )


    # --------------------------------------
    # LOAD SETTINGS
    # --------------------------------------

    cursor.execute(
        "SELECT * FROM alert_settings LIMIT 1"
    )

    settings = cursor.fetchone()

    cursor.close()

    connection.close()

    return render_template(
        "alert_settings.html",
        settings=settings
    )


# ==========================================
# BILLING - CREATE BILL
# ==========================================

@app.route(
    "/billing",
    methods=["GET", "POST"]
)
def billing():

    if "admin" not in session:

        return redirect(url_for("login"))


    connection = get_db_connection()

    cursor = connection.cursor(dictionary=True)


    # --------------------------------------
    # CREATE BILL
    # --------------------------------------

    if request.method == "POST":

        customer_name = request.form["customer_name"]

        customer_phone = request.form.get(
            "customer_phone",
            ""
        )

        medicine_ids = request.form.getlist(
            "medicine_id[]"
        )

        quantities = request.form.getlist(
            "quantity[]"
        )


        bill_items = []

        total_amount = 0

        error = None


        for i in range(len(medicine_ids)):

            if not medicine_ids[i]:
                continue

            medicine_id = int(medicine_ids[i])

            quantity = int(quantities[i])

            if quantity <= 0:
                continue


            cursor.execute(
                "SELECT * FROM medicines WHERE id=%s",
                (medicine_id,)
            )

            medicine = cursor.fetchone()


            if not medicine:
                continue

            if quantity > medicine["quantity"]:

                error = (
                    "Not enough stock for "
                    + medicine["name"]
                    + " (only "
                    + str(medicine["quantity"])
                    + " left)."
                )

                break


            subtotal = round(
                quantity * float(medicine["price"]),
                2
            )

            total_amount += subtotal


            bill_items.append({
                "medicine_id": medicine_id,
                "medicine_name": medicine["name"],
                "quantity": quantity,
                "unit_price": float(medicine["price"]),
                "subtotal": subtotal
            })


        # ----------------------------------
        # VALIDATION FAILED
        # ----------------------------------

        if error:

            cursor.execute(
                "SELECT * FROM medicines WHERE quantity > 0"
            )

            medicines = cursor.fetchall()

            cursor.close()

            connection.close()

            return render_template(
                "billing.html",
                medicines=medicines,
                error=error
            )


        if not bill_items:

            cursor.execute(
                "SELECT * FROM medicines WHERE quantity > 0"
            )

            medicines = cursor.fetchall()

            cursor.close()

            connection.close()

            return render_template(
                "billing.html",
                medicines=medicines,
                error="Please add at least one medicine to the bill."
            )


        # ----------------------------------
        # SAVE BILL
        # ----------------------------------

        cursor.execute(
            """
            INSERT INTO bills
            (customer_name, customer_phone, total_amount)
            VALUES (%s, %s, %s)
            """,
            (
                customer_name,
                customer_phone,
                round(total_amount, 2)
            )
        )

        bill_id = cursor.lastrowid

        today = date.today()


        for item in bill_items:

            cursor.execute(
                """
                INSERT INTO bill_items
                (bill_id, medicine_id, medicine_name, quantity, unit_price, subtotal)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    bill_id,
                    item["medicine_id"],
                    item["medicine_name"],
                    item["quantity"],
                    item["unit_price"],
                    item["subtotal"]
                )
            )

            # Deduct stock
            cursor.execute(
                """
                UPDATE medicines
                SET quantity = quantity - %s
                WHERE id = %s
                """,
                (
                    item["quantity"],
                    item["medicine_id"]
                )
            )

            # Feed the AI Prediction sales history
            cursor.execute(
                """
                INSERT INTO medicine_sales
                (medicine_id, sale_date, quantity_sold)
                VALUES (%s, %s, %s)
                """,
                (
                    item["medicine_id"],
                    today,
                    item["quantity"]
                )
            )


        connection.commit()

        cursor.close()

        connection.close()

        return redirect(
            url_for("view_bill", bill_id=bill_id)
        )


    # --------------------------------------
    # SHOW BILLING FORM
    # --------------------------------------

    cursor.execute(
        "SELECT * FROM medicines WHERE quantity > 0"
    )

    medicines = cursor.fetchall()

    cursor.close()

    connection.close()

    return render_template(
        "billing.html",
        medicines=medicines
    )


# ==========================================
# VIEW / PRINT A SINGLE BILL
# ==========================================

@app.route(
    "/bill/<int:bill_id>"
)
def view_bill(bill_id):

    if "admin" not in session:

        return redirect(url_for("login"))


    connection = get_db_connection()

    cursor = connection.cursor(dictionary=True)


    cursor.execute(
        "SELECT * FROM bills WHERE id=%s",
        (bill_id,)
    )

    bill = cursor.fetchone()


    if not bill:

        cursor.close()

        connection.close()

        return redirect(url_for("sales_history"))


    cursor.execute(
        "SELECT * FROM bill_items WHERE bill_id=%s",
        (bill_id,)
    )

    items = cursor.fetchall()


    cursor.close()

    connection.close()

    return render_template(
        "bill_receipt.html",
        bill=bill,
        items=items
    )


# ==========================================
# SALES HISTORY
# ==========================================

@app.route("/sales_history")
def sales_history():

    if "admin" not in session:

        return redirect(url_for("login"))


    connection = get_db_connection()

    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT *
        FROM bills
        ORDER BY bill_date DESC
        """
    )

    bills = cursor.fetchall()

    cursor.close()

    connection.close()

    return render_template(
        "sales_history.html",
        bills=bills
    )


# ==========================================
# REVENUE REPORTS
# ==========================================

@app.route("/reports")
def reports():

    if "admin" not in session:

        return redirect(url_for("login"))


    connection = get_db_connection()

    cursor = connection.cursor(dictionary=True)


    today = date.today()

    # --------------------------------------
    # TODAY'S REVENUE
    # --------------------------------------

    cursor.execute(
        """
        SELECT COALESCE(SUM(total_amount), 0) AS total
        FROM bills
        WHERE DATE(bill_date) = %s
        """,
        (today,)
    )

    today_total = cursor.fetchone()["total"]


    # --------------------------------------
    # THIS MONTH'S REVENUE
    # --------------------------------------

    cursor.execute(
        """
        SELECT COALESCE(SUM(total_amount), 0) AS total
        FROM bills
        WHERE YEAR(bill_date) = YEAR(%s)
        AND MONTH(bill_date) = MONTH(%s)
        """,
        (today, today)
    )

    month_total = cursor.fetchone()["total"]


    # --------------------------------------
    # LAST 30 DAYS, DAY BY DAY
    # --------------------------------------

    cursor.execute(
        """
        SELECT
            DATE(bill_date) AS sale_day,
            COUNT(*) AS bill_count,
            SUM(total_amount) AS day_total
        FROM bills
        WHERE bill_date >= %s
        GROUP BY DATE(bill_date)
        ORDER BY sale_day DESC
        """,
        (today - timedelta(days=30),)
    )

    daily_totals = cursor.fetchall()


    cursor.close()

    connection.close()

    return render_template(
        "reports.html",
        today_total=today_total,
        month_total=month_total,
        daily_totals=daily_totals
    )


# ==========================================
# LOGOUT
# ==========================================

@app.route("/logout")
def logout():

    session.pop(
        "admin",
        None
    )

    return redirect(
        url_for("login")
    )


# ==========================================
# RUN APPLICATION
# ==========================================

if __name__ == "__main__":

    scheduler = BackgroundScheduler()

    scheduler.add_job(
        check_medicine_reminders,
        "interval",
        minutes=1
    )

    scheduler.add_job(
        check_inventory_alerts,
        "interval",
        minutes=1
    )

    scheduler.start()

    print("================================")
    print("MediSmartAI Reminder Scheduler Started")
    print("Checking reminders every minute...")
    print("================================")

    app.run(debug=True, use_reloader=False)