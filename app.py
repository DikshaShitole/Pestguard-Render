from flask import Flask, render_template, request, redirect, session
import psycopg2
import requests
import os
import uuid
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY", "fallback-secret")

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ===== DATABASE CONNECTION
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set")

def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


# ===== AUTO TABLE CREATION
def create_tables():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        email VARCHAR(100) NOT NULL,
        password VARCHAR(255) NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pest_info (
        id SERIAL PRIMARY KEY,
        pest_name VARCHAR(100),
        reason TEXT,
        solution TEXT,
        prevention TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS history (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100),
        image VARCHAR(255),
        pest VARCHAR(100),
        confidence FLOAT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    cur.close()
    conn.close()


# ===== FILE TYPE SECURITY
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ================= LOGIN PAGE
@app.route("/")
def login_page():
    return render_template("index.html")


# ================= REGISTER PAGE
@app.route("/register")
def register_page():
    return render_template("register.html")


# ================= REGISTER POST
@app.route("/register", methods=["POST"])
def register():

    username = request.form["username"]
    email = request.form["email"]
    password = generate_password_hash(request.form["password"])

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO users(username,email,password) VALUES(%s,%s,%s)",
            (username, email, password)
        )
        conn.commit()

    except Exception:
        return "Username already exists"

    finally:
        cur.close()
        conn.close()

    return redirect("/")


# ================= LOGIN
@app.route("/login", methods=["POST"])
def login():

    username = request.form["username"]
    password = request.form["password"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT username,password FROM users WHERE username=%s",
        (username,)
    )
    user = cur.fetchone()

    cur.close()
    conn.close()

    if user and check_password_hash(user[1], password):
        session["user"] = username
        return redirect("/dashboard")

    return "Invalid Credentials"


# ================= DASHBOARD
@app.route("/dashboard")
def dashboard():

    if "user" not in session:
        return redirect("/")

    return render_template("dashboard.html", user=session["user"])


# ================= DETECT PAGE
@app.route("/detect")
def detect():

    if "user" not in session:
        return redirect("/")

    return render_template("pest_detect.html")


# ================= PREDICT
@app.route("/predict", methods=["POST"])
def predict():

    if "user" not in session:
        return redirect("/")

    file = request.files["leaf_image"]

    if file.filename == "":
        return "No file selected"

    if not allowed_file(file.filename):
        return "Invalid file type"

    filename = str(uuid.uuid4()) + "_" + secure_filename(file.filename)

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    api = "https://pestguard-ml-backend.onrender.com/predict"

    try:
        with open(filepath, "rb") as f:
            response = requests.post(api, files={"file": f}, timeout=120)

        if response.status_code != 200:
            return "ML Service Error"

        data = response.json()

    except Exception as e:
        return f"Prediction API Error: {str(e)}"

    pest = data.get("prediction", "Unknown")
    confidence = round(data.get("confidence", 0) * 100, 2)

    # ===== SAVE HISTORY =====
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO history(username,image,pest,confidence)
        VALUES(%s,%s,%s,%s)
    """, (session["user"], filename, pest, confidence))

    conn.commit()
    cur.close()
    conn.close()

    # ===== GET PEST INFO =====
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT reason,solution,prevention
        FROM pest_info
        WHERE LOWER(pest_name)=LOWER(%s)
    """, (pest,))

    pest_data = cur.fetchone()

    cur.close()
    conn.close()

    return render_template(
        "result.html",
        pest=pest,
        confidence=confidence,
        solution=pest_data[1] if pest_data else "N/A",
        prevention=pest_data[2] if pest_data else "N/A",
        image="uploads/" + filename
    )


# ================= HISTORY PAGE
@app.route("/history")
def history():

    if "user" not in session:
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT image,pest,confidence,created_at
        FROM history
        WHERE username=%s
        ORDER BY created_at DESC
    """, (session["user"],))

    records = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("history.html", records=records)


# ================= LOGOUT
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")


# ===== AUTO TABLE RUN ON STARTUP
create_tables()

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
