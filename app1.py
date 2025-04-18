import streamlit as st
from streamlit_modal import Modal
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import requests
from google.oauth2.service_account import Credentials

# Google Sheets client setup
def get_gsheet_clients():
    scope = ["https://www.googleapis.com/auth/spreadsheets", 
             "https://www.googleapis.com/auth/drive"]
    
    creds_dict = st.secrets["google_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    return client


# Initialize session state
if "page" not in st.session_state:
    st.session_state.page = "Home"
if "form_data" not in st.session_state:
    st.session_state.form_data = {}
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "show_login_form" not in st.session_state:
    st.session_state.show_login_form = False


# Helper: Clear form
def clear_form():
    st.session_state.form_data = {}
    st.rerun()

# Fetch options
client = get_gsheet_clients()
sheet = client.open("Syllabus_DB")

countries_ws = sheet.worksheet("Countries")
centers_ws = sheet.worksheet("Centers")
batches_ws = sheet.worksheet("Batches")
subjects_ws = sheet.worksheet("Subjects")
faculty_ws = sheet.worksheet("Faculty")
chapters_ws = sheet.worksheet("Subject_Chapter_Map")
master_ws = sheet.worksheet("Central_Weekly_Progress")
pendingEmails_ws = sheet.worksheet('PendingEmails')

@st.cache_data(ttl=600)  # Cache for 10 minutes (adjust as needed)
def get_countries():
    return [row[1] for row in countries_ws.get_all_values()[1:] if len(row) > 1]

@st.cache_data(ttl=600)
def get_centers_by_country():
    return centers_ws.get_all_values()[1:]

@st.cache_data(ttl=600)
def get_batches_data():
    return batches_ws.get_all_values()[1:]

@st.cache_data(ttl=600)
def get_subjects_data():
    return subjects_ws.get_all_values()[1:]

@st.cache_data(ttl=600)
def get_faculty_data():
    return faculty_ws.get_all_values()[1:]

@st.cache_data(ttl=600)
def get_chapter_map():
    return chapters_ws.get_all_values()[1:]


def get_master_data():
    return master_ws.get_all_values()[1:]  # Skip header


countries = get_countries()

def get_centers(selected_country):
    all_centers = get_centers_by_country()
    return [row[2] for row in all_centers if len(row) > 2 and row[1] == selected_country]

def get_batches(selected_center):
    all_batches = get_batches_data()
    return [row[2] for row in all_batches if len(row) > 2 and row[1] == selected_center]

def get_subjects():
    return sorted(set(row[1] for row in get_subjects_data() if len(row) > 1))

def get_faculty(selected_center, subject):
    return [row[1] for row in get_faculty_data() if len(row) > 3 and row[2] == selected_center and row[3] == subject]

def get_chapters(subject):
    return sorted(set(row[3] for row in get_chapter_map() if len(row) > 3 and row[1] == subject))

def submit_to_progress_sheet(form_data):
    sheet_name = form_data['Center'] + "_Progress"
    try:
        progress_ws = sheet.worksheet(sheet_name)
    except:
        st.error(f"Sheet '{sheet_name}' not found.")
        return

    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        form_data['Batch'],
        form_data['Subject'],
        form_data['Faculty'],
        ", ".join(form_data['Chapters']),
        str(form_data['Week']),"0"
    ]
    progress_ws.append_row(row)

def merge_weekly_to_master(sheet):

    # Load reference data
    batches_data = batches_ws.get_all_values()[1:]  # Skip header
    centers_data = centers_ws.get_all_values()[1:]

    # Build lookup maps
    batch_to_center = {row[2]: row[1] for row in batches_data if len(row) > 2}  # Batch ID → Center
    center_to_country = {row[2]: row[1] for row in centers_data if len(row) > 2}  # Center → Country

    # Identify progress sheets
    progress_sheets = [ws for ws in sheet.worksheets() if ws.title.endswith("_Progress") and ws.title != "Central_Weekly_Progress"]

    # Check for existing entries in the master sheet
    existing_master_data = master_ws.get_all_values()[1:]

    for ws in progress_sheets:
        rows = ws.get_all_values()
        headers = rows[0]
        data = rows[1:]
        
        for i, row in enumerate(data, start=2):  # start=2 for correct row number (1-based + header)
            # Skip if row is empty or already synced
            if len(row) < 7 or row[6].strip() in ["1", "TRUE", "true"]:
                continue

            try:
                batch_id = row[1]
                center = batch_to_center.get(batch_id, "Unknown Center")
                country = center_to_country.get(center, "Unknown Country")
                week = str(row[5])  # Week is in the 6th column (0-based index 5)

                # Check for duplication in the master sheet based on (center, batch, subject, week)
                duplicate_found = any(
                    existing_row[2] == center and
                    existing_row[3] == batch_id and
                    existing_row[4] == row[2] and  # Subject is in the 3rd column (0-based index 2)
                    existing_row[5] == week
                    for existing_row in existing_master_data
                )

                if duplicate_found:
                    continue  # Skip this row if a duplicate entry exists

                from datetime import datetime
                sync_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                master_row = [sync_timestamp, country, center] + row[1:6]

                # Append the row to the master sheet
                master_ws.append_row(master_row)

                # Mark as synced in the original sheet
                ws.update_acell(f"G{i}", "1")

            except Exception as e:
                st.warning(f"⚠️ Skipped a row in {ws.title} due to error: {e}")

def safe_post_with_retry(url, payload, max_retries=3, timeout=10):
    attempt = 0
    backoff = 2  # seconds to wait before retrying

    while attempt < max_retries:
        try:
            response = requests.post(url, json=payload, timeout=timeout)

            if response.status_code == 200:
                return True, "✅ Success: " + response.text
            else:
                attempt += 1
                print(f"⚠️ Attempt {attempt}: Failed with status {response.status_code}. Retrying in {backoff} seconds...")
                time.sleep(backoff)
                backoff *= 2  # Exponential backoff

        except Exception as e:
            attempt += 1
            print(f"⚠️ Attempt {attempt}: Exception occurred: {e}. Retrying in {backoff} seconds...")
            time.sleep(backoff)
            backoff *= 2

    return False, f"❌ All {max_retries} retries failed."


def notify_via_gas(center, email, batch_id, week):
    # Step 1: Append entry to PendingEmails sheet
    try:
       # Append row
       pendingEmails_ws.append_row([
            str(datetime.now()), 
            center, 
            email, 
            batch_id, 
            week, 
            "Pending"
        ])
    except Exception as e:
        print(f"⚠️ Error appending to sheet: {str(e)}")
        return f"⚠️ Error appending to sheet: {str(e)}"

    # Step 2: Trigger Apps Script to send emails
    url = "https://script.google.com/macros/s/AKfycbz_pqgwlTdyfkJJmgYGNy9zEDagBmKemTJyiAk36xgtwVNQ8qa2tUcIM9Ge9WY31gsOrg/exec"
    payload = {
        "action": "sendPendingEmailsNow"  # Adjust in GAS to understand this
    }

    success, message = safe_post_with_retry(url, payload)



# Home Page
if st.session_state.page == "Home": 
    # Centered Title using markdown and CSS
    st.markdown("""
    <style>
    .main-title {
        font-family: 'Poppins', sans-serif;
        text-align: center;
        font-size: 3.5rem;
        font-weight: 600;
        color: #2C3E50;
        margin-top: 30px;
        margin-bottom: 10px;
    }
    .subtitle {
        text-align: center;
        font-size: 1.5rem;
        font-weight: 300;
        color: #95A5A6;
        margin-bottom: 30px;
    }
    </style>
    <div class="main-title">🌎 GLOBAL ED-TECH</div>
    <div class="subtitle">Empowering Learning, Globally</div>
""", unsafe_allow_html=True)

    # Add vertical spacing to push buttons down
    st.markdown("<div style='height: 20vh;'></div>", unsafe_allow_html=True)
    
    # Get admin credentials from st.secrets
    ADMIN_USERNAME = st.secrets["credentials"]["admin_username"]
    ADMIN_PASSWORD = st.secrets["credentials"]["admin_password"]

    # Check if user is already logged in by checking session state
    
    col1, col2, col3 = st.columns([2,1,1])

    with col1:
        if st.button("📝Update Weekly Progress", use_container_width=True):
            st.session_state.page = "Update"
            st.rerun()
    with col3:
            if st.button("🔒Admin Access"):
                st.session_state.show_login_form = True  # Toggle login form display
                st.session_state.page = "Home"  # Stay on home while login form shows
                st.rerun()
    # --- Styling for expander ---
    st.markdown("""
        <style>
        div.streamlit-expanderHeader {
            font-size: 1.5rem;
            font-weight: 600;
            color: #3498DB;
        }
        .stTextInput>div>div>input {
            font-size: 1.2rem;
            padding: 10px;
        }
        .stButton>button {
            font-size: 1.1rem;
            padding: 10px 20px;
            border-radius: 8px;
            background-color: #3498DB;
            color: white;
            border: none;
            transition: background-color 0.3s;
        }
        .stButton>button:hover {
            background-color: #1ABC9C;
        }
        </style>
    """, unsafe_allow_html=True)

    # Now outside the button condition, check if login form should be shown
    if st.session_state.show_login_form and not st.session_state.logged_in:
        with st.expander("🔐 Admin Login", expanded=True):
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            login_btn = st.button("Login Now")

            if login_btn:
                if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                    st.success("✅ Login successful!")
                    st.session_state.logged_in = True
                    st.session_state.page = "Admin"
                    st.session_state.show_login_form = False
                    st.rerun()
                else:
                    st.error("❌ Incorrect username or password. Try again.")

    # After login
    if st.session_state.logged_in and st.session_state.page == "Admin":
        st.title("🔒 Admin Dashboard")


# Admin Dashboard
if st.session_state.logged_in:
    # Admin-specific content
    st.write("Welcome, Admin!")


if st.session_state.page == "Admin":
    if "missing_batches" not in st.session_state:
        st.session_state.missing_batches = []

    if 'notified_batches' not in st.session_state:
        st.session_state.notified_batches = set()

    if 'last_notified_time' not in st.session_state:
        st.session_state.last_notified_time = dict()


    # Centered Title using markdown and CSS
    st.markdown("<h1 style='text-align: center;'>👩‍💼 Admin Dashboard</h1>", unsafe_allow_html=True)

    # Create 3 columns with width ratios to control spacing
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        if st.button("Merge Progress Data"):
            merge_weekly_to_master(sheet)
            st.success("✅ Progress data merged!")

    with col2:
        week_number = st.number_input("Week Number", min_value=1, step=1)

    with col3:
        check_button = st.button("Check Missing Submissions")
    
    st.markdown("---")

    # Put all disabled buttons in a single row
    reg_col1, reg_col2, reg_col3, reg_col4, reg_col5 = st.columns(5)
    with reg_col1:
        st.button("Register Country", disabled=True)
    with reg_col2:
        st.button("Register Center", disabled=True)
    with reg_col3:
        st.button("Register Batch", disabled=True)
    with reg_col4:
        st.button("Register Subject", disabled=True)
    with reg_col5:
        st.button("Register Faculty", disabled=True)

    st.markdown("")

    col1, col2, col3 = st.columns([2,2,1])

    with col1:
        st.markdown(
            """
            <a href="https://drive.google.com/uc?export=download&id=1g3wYQH0HD5XLxpVD0kCXLJ0OmZqMn-LI" target="_blank">
                <button style="background-color:#1a73e8;color:white;padding:10px 16px;border:none;border-radius:5px;cursor:pointer;">
                    📊 Power BI Dashboard
                </button>
            </a>
            """,
            unsafe_allow_html=True
        )

    with col3:
        # Add a logout button
        if st.button("Logout"):
            st.session_state.logged_in = False  # Reset login status
            st.session_state.page = "Home"  # Redirect to home page or initial page
            st.rerun()  # Rerun the app to reflect changes


    if check_button or st.session_state.missing_batches:

        if check_button:
        # Fetch and store missing entries
            active_batches = [row for row in get_batches_data() if len(row) >= 3]
            batch_to_center = {row[2]: row[1] for row in active_batches}
            center_data = get_centers_by_country()
            center_email_map = {row[2]: row[3] for row in center_data if len(row) > 3}
            master_ws = sheet.worksheet("Central_Weekly_Progress")
            master_data = master_ws.get_all_values()[1:]

            submitted = set((row[3], row[7]) for row in master_data if len(row) > 5)

            missing = []
            for row in active_batches:
                batch_id = row[2]
                center = row[1]
                if (batch_id, str(week_number)) not in submitted:
                    email = center_email_map.get(center, "N/A")
                    missing.append({
                        "Country": row[0] if len(row) > 0 else "Unknown",
                        "Center": center,
                        "Batch ID": batch_id,
                        "Email": email
                    })

            st.session_state.missing_batches = missing
            st.session_state.notified_batches = set()  # Reset notifications on re-check
            st.session_state.last_notified_time = dict()  # ALSO reset last_notified_time

        
        if st.session_state.missing_batches:
            st.warning(f"{len(st.session_state.missing_batches)} batches have not submitted Progress for Week {week_number}.")

            for entry in st.session_state.missing_batches:
                with st.container():
                    cols = st.columns([2, 2, 2, 3, 2])
                    cols[0].markdown(f"{entry['Center']}")
                    cols[1].markdown(f"{entry['Batch ID']}")

                    key = f"notify_{entry['Batch ID']}"

                    already_notified = entry['Batch ID'] in st.session_state.notified_batches

                    notify_button = cols[2].button(
                        "Notify" if not already_notified else "Notified ✅",
                        key=key,
                        disabled=already_notified
                    )

                    # If notify button clicked
                    if notify_button and not already_notified:
                        result = notify_via_gas(entry['Center'], entry['Email'], entry['Batch ID'], week_number)

                        # Update session state
                        st.session_state.notified_batches.add(entry['Batch ID'])
                        st.session_state.last_notified_time[entry['Batch ID']] = time.time()
                        
                        # ✅ Save a success message into session state
                        st.session_state.success_message = f"📧 Notified {entry['Center']} to submit Week {week_number} progress."

                        # ✅ Trigger rerun
                        st.rerun()

                    # After possible rerun, show success message if available
                    if "success_message" in st.session_state:
                        st.success(st.session_state.success_message)
                        # 🧹 Optional: Clear after showing
                        del st.session_state.success_message

                    # Show timer if already notified
                    if already_notified and entry['Batch ID'] in st.session_state.last_notified_time:
                        seconds_ago = int(time.time() - st.session_state.last_notified_time[entry['Batch ID']])
                        minutes_ago = seconds_ago // 60

                        if minutes_ago == 0:
                            cols[3].markdown(f"✅ Notified just now")
                        else:
                            cols[3].markdown(f"⏰ Notified {minutes_ago} min ago")

            # If no missing batches
            if not st.session_state.missing_batches:
                st.success("✅ All active batches have submitted their progress for this week.")
            else:
                if st.button("Clear Results"):
                    st.session_state.missing_batches = []
                    st.session_state.notified_batches = set()
                    st.session_state.last_notified_time = dict()
                    st.rerun()

        
# Update Weekly Progress Page
elif st.session_state.page == "Update":
    st.title("📝 Weekly Progress Form")

    # Country selection
    selected_country = st.selectbox(
        "🏫 **Country** *", ["Choose Country"] + countries,
        key="selected_country"
    )

    # Center selection based on country
    center_options = get_centers(selected_country) if selected_country != "Choose Country" else []
    selected_center = st.selectbox(
        "🏫 **Center** *", ["Choose Center"] + center_options,
        key="selected_center"
    )

    # Batch selection based on center
    batch_options = get_batches(selected_center) if selected_center != "Choose Center" else []
    selected_batch = st.selectbox(
        "🎓 **Batch ID** *", ["Choose Batch ID"] + batch_options,
        key="selected_batch"
    )

    # Subject options from Batches table
    subject_options = []
    if selected_batch and selected_batch != "Choose Batch ID":
        for row in batches_ws.get_all_values()[1:]:
            if len(row) > 5 and row[2] == selected_batch:
                subject_options = [s.strip() for s in row[5].split(",") if s.strip()]
                break
    subject = st.selectbox("**Subject** ❗", options=["Choose Subject"] + subject_options, key="selected_subject")

    # Faculty options based on center + subject
    faculty_options = []
    if selected_center != "Choose Center" and subject != "Choose Subject":
        faculty_options = [
            row[1] for row in faculty_ws.get_all_values()[1:]
            if len(row) > 3 and row[2] == selected_center and row[3] == subject
        ]
    faculty = st.selectbox("**Faculty** ❗", options=["Choose Faculty"] + faculty_options, key="selected_faculty")

    # Chapter options from map
    chapter_options = get_chapters(subject) if subject != "Choose Subject" else []

    # Now build the actual forms
    with st.form("progress_form"):
        chapters = st.multiselect("**Chapters Completed** ❗", options=chapter_options, key="selected_chapters")
        week = st.number_input("**Week Number** ❗", min_value=1, max_value=30, step=1, key="selected_week")

        col1, col2, col3 = st.columns(3)
        with col1:
            submitted = st.form_submit_button("✅ Submit")
        with col2:
            cleared = st.form_submit_button("🧹 Clear")
        with col3:
            home = st.form_submit_button("🏠 Home")

        if submitted:
            if (selected_country == "Choose Country" or
                    selected_center == "Choose Center" or
                    selected_batch == "Choose Batch ID" or
                    subject == "Choose Subject" or
                    faculty == "Choose Faculty" or
                    not chapters or not week):
                st.error("Please fill in all fields.")
            else:
                form_data = {
                        "Country": selected_country,
                        "Center": selected_center,
                        "Batch": selected_batch,
                        "Subject": subject,
                        "Faculty": faculty,
                        "Chapters": chapters,
                        "Week": week
                    }
                submit_to_progress_sheet(form_data)
                st.success("✅ Progress submitted!")
                st.rerun()
        elif cleared:
            keys_to_clear = [
                "selected_country", "selected_center", "selected_batch",
                "selected_subject", "selected_faculty", "selected_chapters", "selected_week"
            ]
            for k in keys_to_clear:
                st.session_state.pop(k, None)  # safer: pop with default
            st.rerun()
        elif home:
            st.session_state.page = "Home"
            st.rerun()

