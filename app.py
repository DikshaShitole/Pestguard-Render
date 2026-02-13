from flask import Flask, render_template, request, redirect, session
import psycopg2
import requests
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY")

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ===== DATABASE CONNECTION
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set")

def get_db():
    return psycopg2.connect(DATABASE_URL)


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

    except:
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

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    file.save(filepath)

    # ===== CALL ML API
    api = "https://pestguard-ml-backend.onrender.com/predict"

    try:
        with open(filepath, "rb") as f:
            response = requests.post(api, files={"file": f}, timeout=15)

        if response.status_code != 200:
            return "ML Service Error"

        data = response.json()

    except Exception as e:
        return f"Prediction API Error: {str(e)}"

    pest = data.get("prediction", "Unknown")
    confidence = round(data.get("confidence", 0) * 100, 2)

    # ===== FETCH DB DATA
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


# ================= LOGOUT
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")


if __name__ == "__main__":
    app.run(debug=True)
