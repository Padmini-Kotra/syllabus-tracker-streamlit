import streamlit as st
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
    # Load worksheets
    batches_ws = sheet.worksheet("Batches")
    centers_ws = sheet.worksheet("Centers")
    master_ws = sheet.worksheet("Central_Weekly_Progress")

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

import requests

def notify_via_gas(center, email, batch_id, week):
    url = "https://script.google.com/macros/s/AKfycbwxepWUExiZ1XCeUuZyOnrU3jWLg1-tm77GAKrbVgstXE5Aqag4LhE80D2KL3s1ilXhXw/exec"
    payload = {
        "centerName": center,
        "emailAddress": email,
        "batchId": batch_id,
        "week": week
    }

    try:
        response = requests.post(url, json=payload)  # Ensure the data is sent as JSON
        if response.status_code == 200:
            return "Email sent!"
        else:
            return f"❌ Failed: {response.text}"
    except Exception as e:
        return f"⚠️ Error: {str(e)}"


# Home Page
if st.session_state.page == "Home": 
    # Centered Title using markdown and CSS
    st.markdown("""
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@500&display=swap" rel="stylesheet">
        <style>
        .title-text {
            text-align: center;
            font-family: 'Poppins', sans-serif;
            font-size: 3em;
            color: #1E4D2B;
            margin-top: 30px;
        }
        </style>
        <div class="title-text">GLOBAL ED-TECH</div>
    """, unsafe_allow_html=True)

    # Add vertical spacing to push buttons down
    st.markdown("<div style='height: 20vh;'></div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([2,1,1])

    with col1:
        if st.button("📝Update Weekly Progress", use_container_width=True):
            st.session_state.page = "Update"
            st.rerun()
    with col3:
            if st.button("🔒Admin Access"):
                st.session_state.page = "Admin"
                st.rerun()

# Admin Dashboard
if st.session_state.page == "Admin":
    if "missing_batches" not in st.session_state:
        st.session_state.missing_batches = []

    if "notified_batches" not in st.session_state:
        st.session_state.notified_batches = set()

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
        
        if st.session_state.missing_batches:
            st.warning(f"{len(st.session_state.missing_batches)} batches have not submitted Progress for Week {week_number}.")

            for entry in st.session_state.missing_batches:
                with st.container():
                    cols = st.columns([2, 2, 2, 3, 2])
                    cols[0].markdown(f"{entry['Center']}")
                    cols[1].markdown(f"{entry['Batch ID']}")

                    key = f"notify_{entry['Batch ID']}"
                    if cols[2].button("Notify", key=key):
                        if entry['Batch ID'] not in st.session_state.notified_batches:
                            result = notify_via_gas(entry['Center'], entry['Email'], entry['Batch ID'], week_number)
                            st.session_state.notified_batches.add(entry['Batch ID'])
                            st.success(f"📧 Notified {entry['Center']} to submit Week {week_number} progress.")
                        else:
                            st.info(f"Already notified {entry['Center']}.")
        else:
            st.success("✅ All active batches have submitted their progress for this week.")

    
        if st.button("Clear Results"):
            st.session_state.missing_batches = []
            st.session_state.notified_batches = set()

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
        st.markdown(
        """
        <form action="#">
            <button type="submit" name="home_button" style="background-color:#28a745;color:white;padding:12px 20px;font-size:16px;border:none;border-radius:8px;cursor:pointer;">
                🏠 Home
            </button>
        </form>
        """,
        unsafe_allow_html=True
        )

    # Detect if the "home_button" form was submitted
    if "home_button" in st.session_state.get("query_params", {}):
        st.session_state.page = "Home"
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
                for k in ["selected_country", "selected_center", "selected_batch", "selected_subject", "selected_faculty", "selected_chapters", "selected_week"]:
                    if k in st.session_state:
                        del st.session_state[k]
                st.rerun()
        elif home:
            st.session_state.page = "Home"
            st.rerun()
        
