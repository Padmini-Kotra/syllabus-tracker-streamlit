import streamlit as st
import gspread
from google.oauth2.service_account import Credentials # Use google-auth library
from datetime import datetime
import requests # Keep requests in case it's used elsewhere, otherwise removable
from typing import List, Dict, Any, Set, Optional

# --- Constants ---
# Recommended: Store credentials in Streamlit Secrets
# See: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
# Example secrets.toml:
# [google_sheets]
# credentials = """
# {
#   "type": "service_account",
#   "project_id": "your-project-id",
#   "private_key_id": "your-private-key-id",
#   # ... other fields from your credentials.json ...
#   "private_key": "-----BEGIN PRIVATE KEY-----\nYOUR_PRIVATE_KEY\n-----END PRIVATE KEY-----\n",
#   "client_email": "your-service-account-email@your-project-id.iam.gserviceaccount.com",
#   "client_id": "your-client-id",
#   "auth_uri": "https://accounts.google.com/o/oauth2/auth",
#   "token_uri": "https://oauth2.googleapis.com/token",
#   "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
#   "client_x509_cert_url": "..."
# }
# """
# CREDENTIALS_PATH = "credentials/credentials.json" # Old way

SPREADSHEET_NAME = "Syllabus_DB"
SHEET_COUNTRIES = "Countries"
SHEET_CENTERS = "Centers"
SHEET_BATCHES = "Batches"
SHEET_SUBJECTS = "Subjects"
SHEET_FACULTY = "Faculty"
SHEET_CHAPTER_MAP = "Subject_Chapter_Map"
SHEET_MASTER_PROGRESS = "Central_Weekly_Progress"
PROGRESS_SHEET_SUFFIX = "_Progress"

# Column Indices (0-based) for clarity - Adjust if sheet structure changes
# Example for Centers sheet:
IDX_CENTER_COUNTRY = 1
IDX_CENTER_NAME = 2
IDX_CENTER_EMAIL = 3
# Add other indices as needed for different sheets...
IDX_BATCH_CENTER = 1
IDX_BATCH_ID = 2
IDX_BATCH_SUBJECTS = 5

IDX_MASTER_CENTER = 2
IDX_MASTER_BATCH_ID = 3
IDX_MASTER_SUBJECT = 4
IDX_MASTER_WEEK = 5
IDX_MASTER_SYNC_TIMESTAMP=0
IDX_MASTER_COUNTRY=1


# GAS_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzOXnE-dJsXTvZh_bE_QrFE37a-tTzjLywbMLruWDH9YJddDt7iXtXG_xYQ2nnDRnO0/exec" # Removed GAS functionality

# --- Google Sheets Client Setup ---
@st.cache_resource(ttl=600) # Cache resource for 10 mins
def get_gspread_client():
    """Authorizes and returns a gspread client using Streamlit Secrets."""
    try:
        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        # Load credentials from Streamlit secrets
        creds_dict = st.secrets["google_sheets"]["credentials"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        return client
    except KeyError:
        st.error("🚨 Google Sheets credentials not found in Streamlit Secrets. Please configure `[google_sheets.credentials]` in your secrets.")
        st.stop()
    except Exception as e:
        st.error(f"Failed to authorize Google Sheets client: {e}")
        st.stop() # Stop execution if client fails

@st.cache_resource(ttl=600)
def get_gspread_client():
    """Authorizes and returns a gspread client using Streamlit Secrets."""
    try:
        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        # Load credentials value from Streamlit secrets
        creds_value = st.secrets["google_sheets"]["credentials"]

        creds_dict = None
        # Check if the retrieved value is a string (needs parsing) or dict (ideal)
        if isinstance(creds_value, str):
            st.warning("Attempting to parse Google Sheets credentials from string in secrets. Ensure correct TOML format for automatic parsing.")
            try:
                # Attempt to parse the string as JSON
                creds_dict = json.loads(creds_value)
            except json.JSONDecodeError as json_err:
                st.error(f"🚨 Failed to parse Google Sheets credentials from secrets string as JSON: {json_err}")
                st.error("Please ensure the 'credentials' value in secrets.toml contains a valid JSON string, ideally enclosed in triple quotes (`\"\"\"`).")
                st.stop()
        elif isinstance(creds_value, dict):
            # Assume it's already a dictionary (correct TOML formatting)
            creds_dict = creds_value
        else:
            # Handle unexpected type
            st.error(f"🚨 Unexpected type for Google Sheets credentials in secrets: {type(creds_value)}. Expected string or dict.")
            st.stop()

        # Proceed only if we have a dictionary
        if creds_dict is None:
             st.error("🚨 Failed to load credentials dictionary.") # Should not happen if logic above is correct, but safety check
             st.stop()

        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        st.success("Google Sheets client authorized successfully.") # Optional success message
        return client

    except KeyError:
        st.error("🚨 Google Sheets credentials not found in Streamlit Secrets. Please configure `[google_sheets.credentials]` in your secrets.toml.")
        st.stop()
    except Exception as e:
        # Catch potential errors during Credentials.from_service_account_info or gspread.authorize
        st.error(f"Failed to authorize Google Sheets client: {e}")
        st.stop() # Stop execution if client fails

@st.cache_data(ttl=600) # Cache data for 10 mins
def fetch_worksheet_data(_sheet: gspread.Spreadsheet, worksheet_name: str) -> List[List[str]]:
    """Fetches all data from a worksheet, skipping the header row."""
    try:
        worksheet = _sheet.worksheet(worksheet_name)
        data = worksheet.get_all_values()
        return data[1:] if len(data) > 1 else []
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Worksheet '{worksheet_name}' not found in '{_sheet.title}'.")
        return []
    except Exception as e:
        st.error(f"Failed to fetch data from '{worksheet_name}': {e}")
        return []

# --- Data Fetching Functions ---
def get_countries_list(sheet: gspread.Spreadsheet) -> List[str]:
    """Fetches the list of country names."""
    data = fetch_worksheet_data(sheet, SHEET_COUNTRIES)
    # Assuming country name is in the second column (index 1)
    return sorted([row[1] for row in data if len(row) > 1 and row[1]])

def get_centers_data(sheet: gspread.Spreadsheet) -> List[List[str]]:
    """Fetches all center data."""
    return fetch_worksheet_data(sheet, SHEET_CENTERS)

def get_batches_data(sheet: gspread.Spreadsheet) -> List[List[str]]:
    """Fetches all batch data."""
    return fetch_worksheet_data(sheet, SHEET_BATCHES)

def get_subjects_data(sheet: gspread.Spreadsheet) -> List[List[str]]:
    """Fetches all subject data."""
    return fetch_worksheet_data(sheet, SHEET_SUBJECTS)

def get_faculty_data(sheet: gspread.Spreadsheet) -> List[List[str]]:
    """Fetches all faculty data."""
    return fetch_worksheet_data(sheet, SHEET_FACULTY)

def get_chapter_map_data(sheet: gspread.Spreadsheet) -> List[List[str]]:
    """Fetches the subject-chapter mapping data."""
    return fetch_worksheet_data(sheet, SHEET_CHAPTER_MAP)

def get_master_progress_data(sheet: gspread.Spreadsheet) -> List[List[str]]:
    """Fetches data from the central progress sheet."""
    return fetch_worksheet_data(sheet, SHEET_MASTER_PROGRESS)

# --- Helper Functions for Filtering Data ---
def get_centers_for_country(centers_data: List[List[str]], selected_country: str) -> List[str]:
    """Filters centers based on the selected country."""
    # Assumes country is index 1, center name is index 2
    return sorted([row[IDX_CENTER_NAME] for row in centers_data if len(row) > IDX_CENTER_NAME and row[IDX_CENTER_COUNTRY] == selected_country])

def get_batches_for_center(batches_data: List[List[str]], selected_center: str) -> List[str]:
    """Filters batches based on the selected center."""
    # Assumes center is index 1, batch ID is index 2
    return sorted([row[IDX_BATCH_ID] for row in batches_data if len(row) > IDX_BATCH_ID and row[IDX_BATCH_CENTER] == selected_center])

def get_subjects_for_batch(batches_data: List[List[str]], selected_batch: str) -> List[str]:
    """Gets the list of subjects associated with a specific batch."""
    for row in batches_data:
        if len(row) > IDX_BATCH_SUBJECTS and row[IDX_BATCH_ID] == selected_batch:
            # Assumes subjects are comma-separated in index 5
            return sorted([s.strip() for s in row[IDX_BATCH_SUBJECTS].split(',') if s.strip()])
    return []

def get_faculty_for_center_subject(faculty_data: List[List[str]], selected_center: str, selected_subject: str) -> List[str]:
    """Filters faculty based on selected center and subject."""
    # Assumes faculty name is index 1, center is index 2, subject is index 3
    return sorted([row[1] for row in faculty_data if len(row) > 3 and row[2] == selected_center and row[3] == selected_subject])

def get_chapters_for_subject(chapter_map_data: List[List[str]], selected_subject: str) -> List[str]:
    """Filters chapters based on the selected subject."""
    # Assumes subject is index 1, chapter is index 3
    return sorted(list(set(row[3] for row in chapter_map_data if len(row) > 3 and row[1] == selected_subject)))

# --- Core Logic Functions ---
def submit_to_progress_sheet(sheet: gspread.Spreadsheet, form_data: Dict[str, Any]) -> bool:
    """Appends submitted form data to the center-specific progress sheet."""
    sheet_name = f"{form_data['Center']}{PROGRESS_SHEET_SUFFIX}"
    try:
        progress_ws = sheet.worksheet(sheet_name)
        row_to_append = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            form_data['Batch'],
            form_data['Subject'],
            form_data['Faculty'],
            ", ".join(form_data['Chapters']),
            str(form_data['Week']),
            "0" # Mark as not synced (0 or FALSE)
        ]
        progress_ws.append_row(row_to_append)
        return True
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Sheet '{sheet_name}' not found. Please ensure it exists.")
        return False
    except Exception as e:
        st.error(f"Failed to submit progress to '{sheet_name}': {e}")
        return False

def merge_weekly_to_master(sheet: gspread.Spreadsheet) -> None:
    """Merges unsynced data from center progress sheets to the master progress sheet."""
    try:
        master_ws = sheet.worksheet(SHEET_MASTER_PROGRESS)
        batches_data = get_batches_data(sheet)
        centers_data = get_centers_data(sheet)
        existing_master_data = master_ws.get_all_values()[1:] # Skip header

        # Build lookup maps more robustly
        batch_to_center = {row[IDX_BATCH_ID]: row[IDX_BATCH_CENTER] for row in batches_data if len(row) > IDX_BATCH_ID}
        center_to_country = {row[IDX_CENTER_NAME]: row[IDX_CENTER_COUNTRY] for row in centers_data if len(row) > IDX_CENTER_NAME}

        # Create a set of existing keys for faster lookup
        # Key: (Center, BatchID, Subject, Week)
        existing_keys = set()
        for row in existing_master_data:
            if len(row) > max(IDX_MASTER_CENTER, IDX_MASTER_BATCH_ID, IDX_MASTER_SUBJECT, IDX_MASTER_WEEK):
                 existing_keys.add((
                     row[IDX_MASTER_CENTER],
                     row[IDX_MASTER_BATCH_ID],
                     row[IDX_MASTER_SUBJECT],
                     str(row[IDX_MASTER_WEEK]) # Ensure week is compared as string
                 ))


        progress_sheets = [ws for ws in sheet.worksheets() if ws.title.endswith(PROGRESS_SHEET_SUFFIX) and ws.title != SHEET_MASTER_PROGRESS]
        merged_count = 0

        st.write(f"Found {len(progress_sheets)} progress sheets to check.")

        for ws in progress_sheets:
            try:
                rows = ws.get_all_values()
                if len(rows) <= 1: continue # Skip if only header or empty

                data_to_sync = []
                updates_to_make = [] # List of (cell, value) tuples for batch update

                for i, row in enumerate(rows[1:], start=2): # start=2 for 1-based index + header offset
                    # Check if row has enough columns and is not already synced (column G, index 6)
                    if len(row) < 7 or str(row[6]).strip() in ["1", "TRUE", "true"]:
                        continue

                    # Extract data (assuming progress sheet columns: Timestamp, Batch, Subject, Faculty, Chapters, Week, Synced)
                    batch_id = row[1]
                    subject = row[2]
                    week = str(row[5])
                    center = batch_to_center.get(batch_id, "Unknown Center")
                    country = center_to_country.get(center, "Unknown Country")

                    # Check for duplicates in master sheet using the pre-built set
                    entry_key = (center, batch_id, subject, week)
                    if entry_key in existing_keys:
                        # If already in master, mark as synced in source if not already
                        if str(row[6]).strip() not in ["1", "TRUE", "true"]:
                             updates_to_make.append((f"G{i}", "1"))
                        continue # Skip adding to master

                    # Prepare row for master sheet (Timestamp, Country, Center, Batch, Subject, Faculty, Chapters, Week)
                    # Note: Master sheet structure might differ, adjust indices accordingly
                    sync_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    master_row = [sync_timestamp, country, center] + row[1:6] # Slices includes Batch, Subject, Faculty, Chapters, Week

                    data_to_sync.append(master_row)
                    updates_to_make.append((f"G{i}", "1")) # Mark for sync update
                    existing_keys.add(entry_key) # Add to known keys to prevent duplicates within this run

                # Batch append data to master sheet
                if data_to_sync:
                    master_ws.append_rows(data_to_sync, value_input_option='USER_ENTERED')
                    merged_count += len(data_to_sync)
                    st.write(f"Appended {len(data_to_sync)} rows from {ws.title} to master.")


                # Batch update sync status in the source sheet
                if updates_to_make:
                    ws.batch_update(updates_to_make, value_input_option='USER_ENTERED')
                    st.write(f"Marked {len(updates_to_make)} rows as synced in {ws.title}.")


            except Exception as e:
                st.warning(f"⚠️ Skipped processing sheet '{ws.title}' due to error: {e}")

        if merged_count > 0:
            st.success(f"✅ Merged a total of {merged_count} new progress records into '{SHEET_MASTER_PROGRESS}'.")
        else:
            st.info("ℹ️ No new progress records found to merge.")

    except gspread.exceptions.WorksheetNotFound:
         st.error(f"Master worksheet '{SHEET_MASTER_PROGRESS}' not found.")
    except Exception as e:
        st.error(f"An error occurred during the merge process: {e}")

# --- Removed GAS Notification Function ---
# def notify_via_gas(center: str, email: str, batch_id: str, week: int) -> str:
#     """Sends a notification using a Google Apps Script webhook."""
#     payload = {
#         "centerName": center,
#         "emailAddress": email,
#         "batchId": batch_id,
#         "week": week
#     }
#     try:
#         # response = requests.post(GAS_WEBHOOK_URL, json=payload, timeout=10) # Add timeout
#         # response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
#         # Check response content if GAS returns specific success/failure message
#         # Assuming simple success on 200 OK
#         # return f"✅ Notification sent successfully to {center} ({email}) for Batch {batch_id}, Week {week}."
#         pass # Functionality removed
#     except requests.exceptions.Timeout:
#         return f"❌ Timeout error: Failed to send notification for {batch_id}."
#     except requests.exceptions.RequestException as e:
#         return f"❌ Request error: Failed to send notification for {batch_id}. Error: {e}"
#     except Exception as e:
#         return f"⚠️ Unexpected error during notification for {batch_id}: {str(e)}"
#     return "ℹ️ Notification functionality is currently disabled."


# --- Streamlit Page Functions ---

def show_home_page():
    """Renders the Home page."""
    st.markdown("<h1 style='text-align: center;'>GLOBAL ED-TECH</h1>", unsafe_allow_html=True)
    st.markdown("---") # Add a separator
    col1, col2, col3 = st.columns([1, 1, 1]) # Adjust ratios as needed

    with col1:
        if st.button("📝 Update Weekly Progress", use_container_width=True, key="nav_update"):
            st.session_state.page = "Update"
            st.rerun()
    with col3:
        if st.button("🔒 Admin Access", use_container_width=True, key="nav_admin"):
            st.session_state.page = "Admin"
            st.rerun()

def show_admin_page(sheet: gspread.Spreadsheet):
    """Renders the Admin Dashboard page."""
    st.markdown("<h1 style='text-align: center;'>👩‍💼 Admin Dashboard</h1>", unsafe_allow_html=True)

    # Initialize session state for this page if needed
    if "missing_batches" not in st.session_state:
        st.session_state.missing_batches = []
    # Removed notified_batches state as notification is disabled
    # if "notified_batches" not in st.session_state:
    #     st.session_state.notified_batches = set()


    # --- Merge Section ---
    st.subheader("Merge Progress Data")
    if st.button("Merge All Center Progress to Master Sheet", key="merge_data"):
        with st.spinner("Merging data... Please wait."):
            merge_weekly_to_master(sheet)


    st.markdown("---")


    # --- Missing Submissions Section ---
    st.subheader("Check Missing Weekly Submissions")
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        # Placeholder or future use
         pass

    with col2:
        # Default to 1 or perhaps the last checked week?
        week_number = st.number_input("Check for Week Number:", min_value=1, step=1, key="admin_week_check", value=st.session_state.get("last_checked_week", 1))


    with col3:
         st.write("") # Align button vertically
         st.write("")
         check_button = st.button("Check Missing", key="check_missing")


    if check_button:
         st.session_state.last_checked_week = week_number # Remember the week number checked
         with st.spinner(f"Checking submissions for Week {week_number}..."):
            # Fetch necessary data using cached functions
            active_batches_data = get_batches_data(sheet) # Assumes all listed batches are active
            center_data = get_centers_data(sheet)
            master_data = get_master_progress_data(sheet)


            # Process data
            # Assuming batch data has: Country (0), Center (1), Batch ID (2)
            # Assuming center data has: Country (1), Center Name (2), Email (3)
            # Assuming master data has: Center (2), Batch ID (3), Week (5)
            active_batches = [
                 {"country": row[0], "center": row[1], "batch_id": row[2]}
                 for row in active_batches_data if len(row) > 2
            ]


            center_email_map = {row[IDX_CENTER_NAME]: row[IDX_CENTER_EMAIL] for row in center_data if len(row) > IDX_CENTER_EMAIL and row[IDX_CENTER_EMAIL]}


            submitted_this_week = set()
            for row in master_data:
                #Check length before accessing indices
                if len(row) > max(IDX_MASTER_BATCH_ID, IDX_MASTER_WEEK) and str(row[IDX_MASTER_WEEK]).strip() == str(week_number):
                      submitted_this_week.add(row[IDX_MASTER_BATCH_ID])


            missing = []
            for batch in active_batches:
                batch_id = batch["batch_id"]
                if batch_id not in submitted_this_week:
                    center = batch["center"]
                    email = center_email_map.get(center, "N/A - Email not found")
                    missing.append({
                        "Country": batch.get("country", "Unknown"),
                        "Center": center,
                        "Batch ID": batch_id,
                        "Email": email
                    })


            st.session_state.missing_batches = missing
            # st.session_state.notified_batches = set() # Reset notifications on new check - Removed
            st.rerun() # Rerun to display results below


    # Display missing batches (without notification buttons)
    if st.session_state.missing_batches:
        checked_week = st.session_state.get("last_checked_week", "N/A")
        st.warning(f"Found {len(st.session_state.missing_batches)} active batches missing submission for Week {checked_week}.")

        # Remove button styling markdown as buttons are gone
        # st.markdown(...)

        # Adjust columns for displaying info without Notify/Status
        header_cols = st.columns([2, 3, 3]) # Adjusted columns
        header_cols[0].markdown("**Center**")
        header_cols[1].markdown("**Batch ID**")
        header_cols[2].markdown("**Email**")
        # header_cols[3].markdown("**Notify**") # Removed
        # header_cols[4].markdown("**Status**") # Removed


        for idx, entry in enumerate(st.session_state.missing_batches):
            cols = st.columns([2, 3, 3]) # Adjusted columns
            cols[0].markdown(f"{entry['Center']}")
            cols[1].markdown(f"{entry['Batch ID']}")
            cols[2].markdown(f"{entry['Email']}")

            # --- Removed Notification Button Logic ---
            # notification_key = (entry['Batch ID'], checked_week)
            # button_key = f"notify_{entry['Batch ID']}_{checked_week}_{idx}"
            # can_notify = entry['Email'] != "N/A - Email not found" and "@" in entry['Email']
            # if notification_key in st.session_state.notified_batches:
            #     cols[3].button("Notify", key=button_key, disabled=True)
            #     cols[4].success("Notified")
            # elif not can_notify:
            #     cols[3].button("Notify", key=button_key, disabled=True)
            #     cols[4].warning("No Email")
            # else:
            #      if cols[3].button("Notify", key=button_key):
            #         if entry['Email'] and entry['Email'] != "N/A - Email not found":
            #             with st.spinner(f"Notifying {entry['Center']}..."):
            #                 result = notify_via_gas(entry['Center'], entry['Email'], entry['Batch ID'], checked_week)
            #             st.info(result)
            #             if "✅" in result or "successfully" in result.lower():
            #                 st.session_state.notified_batches.add(notification_key)
            #                 st.rerun()
            #             else:
            #                  st.error("Notification failed, see message above.")
            #         else:
            #              st.error("Cannot notify: Email address is missing or invalid.")
            #      else:
            #          cols[4].markdown("Pending")
            # --- End Removed Logic ---

        st.markdown("---")
        if st.button("Clear Missing Results", key="clear_missing_results"):
            st.session_state.missing_batches = []
            # st.session_state.notified_batches = set() # Removed
            st.rerun()


    elif check_button: # Only show success if check was just run and nothing was found
         checked_week = st.session_state.get("last_checked_week", "N/A")
         st.success(f"✅ All active batches appear to have submitted progress for Week {checked_week}.")


    # --- Registration Placeholders ---
    st.markdown("---")
    st.subheader("Registration (Placeholder)")
    reg_col1, reg_col2, reg_col3, reg_col4, reg_col5 = st.columns(5)
    reg_col1.button("Register Country", disabled=True, key="reg_country")
    reg_col2.button("Register Center", disabled=True, key="reg_center")
    reg_col3.button("Register Batch", disabled=True, key="reg_batch")
    reg_col4.button("Register Subject", disabled=True, key="reg_subject")
    reg_col5.button("Register Faculty", disabled=True, key="reg_faculty")


    # --- Navigation ---
    st.markdown("---")
    home_col = st.columns(3)[1] # Center column
    if home_col.button("🏠 Back to Home", use_container_width=True, key="admin_home"):
        st.session_state.page = "Home"
        # Clear admin-specific state if desired when leaving
        if "missing_batches" in st.session_state: del st.session_state.missing_batches
        # if "notified_batches" in st.session_state: del st.session_state.notified_batches # Removed
        if "last_checked_week" in st.session_state: del st.session_state.last_checked_week
        st.rerun()

def show_update_page(sheet: gspread.Spreadsheet):
    """Renders the Weekly Progress Update Form page."""
    st.title("📝 Weekly Progress Form")

    # Fetch data required for dropdowns using cached functions
    countries_list = get_countries_list(sheet)
    all_centers_data = get_centers_data(sheet)
    all_batches_data = get_batches_data(sheet)
    all_faculty_data = get_faculty_data(sheet)
    all_chapter_map_data = get_chapter_map_data(sheet)

    # --- Dropdown Selections ---
    # Use session state to remember selections across reruns
    sel_country = st.selectbox(
        "🌍 **Country** *",
        options=["Choose Country"] + countries_list,
        key="update_sel_country"
    )

    center_options = get_centers_for_country(all_centers_data, sel_country) if sel_country != "Choose Country" else []
    sel_center = st.selectbox(
        "🏫 **Center** *",
        options=["Choose Center"] + center_options,
        key="update_sel_center",
        disabled=(sel_country == "Choose Country")
    )

    batch_options = get_batches_for_center(all_batches_data, sel_center) if sel_center != "Choose Center" else []
    sel_batch = st.selectbox(
        "🎓 **Batch ID** *",
        options=["Choose Batch ID"] + batch_options,
        key="update_sel_batch",
        disabled=(sel_center == "Choose Center")
    )

    subject_options = get_subjects_for_batch(all_batches_data, sel_batch) if sel_batch != "Choose Batch ID" else []
    sel_subject = st.selectbox(
        "📚 **Subject** *",
        options=["Choose Subject"] + subject_options,
        key="update_sel_subject",
        disabled=(sel_batch == "Choose Batch ID")
    )

    faculty_options = get_faculty_for_center_subject(all_faculty_data, sel_center, sel_subject) \
        if sel_center != "Choose Center" and sel_subject != "Choose Subject" else []
    sel_faculty = st.selectbox(
        "🧑‍🏫 **Faculty** *",
        options=["Choose Faculty"] + faculty_options,
        key="update_sel_faculty",
        disabled=(sel_subject == "Choose Subject")
    )

    chapter_options = get_chapters_for_subject(all_chapter_map_data, sel_subject) if sel_subject != "Choose Subject" else []

    # --- Form for Chapters and Week ---
    with st.form("progress_form", clear_on_submit=False): # Keep values on page unless cleared
        sel_chapters = st.multiselect(
            "📖 **Chapters Completed** *",
            options=chapter_options,
            key="update_sel_chapters",
            disabled=(sel_subject == "Choose Subject")
        )
        sel_week = st.number_input(
            "📅 **Week Number** *",
            min_value=1, max_value=52, step=1, # Adjusted max_value
            key="update_sel_week",
            disabled=(sel_subject == "Choose Subject")
        )

        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        submitted = col1.form_submit_button("✅ Submit Progress")
        cleared = col2.form_submit_button("🧹 Clear Form")
        home = col3.form_submit_button("🏠 Back to Home")

        if submitted:
            # Validation check
            if (sel_country == "Choose Country" or
                    sel_center == "Choose Center" or
                    sel_batch == "Choose Batch ID" or
                    sel_subject == "Choose Subject" or
                    sel_faculty == "Choose Faculty" or
                    not sel_chapters or not sel_week):
                st.error("❗ Please fill in all required fields (*).")
            else:
                form_data = {
                    "Country": sel_country,
                    "Center": sel_center,
                    "Batch": sel_batch,
                    "Subject": sel_subject,
                    "Faculty": sel_faculty,
                    "Chapters": sel_chapters,
                    "Week": sel_week
                }
                with st.spinner("Submitting..."):
                    success = submit_to_progress_sheet(sheet, form_data)
                    if success:
                        st.success("✅ Progress submitted successfully!")
                        # Clear form fields in session state after successful submission
                        for key in ["update_sel_country", "update_sel_center", "update_sel_batch",
                                    "update_sel_subject", "update_sel_faculty", "update_sel_chapters",
                                    "update_sel_week"]:
                            if key in st.session_state:
                                # Reset to default/initial state if possible
                                if key in ["update_sel_country", "update_sel_center", "update_sel_batch", "update_sel_subject", "update_sel_faculty"]:
                                     st.session_state[key] = key.split('_')[-1].replace("sel", "Choose ").capitalize() # Heuristic reset
                                elif key == "update_sel_chapters":
                                     st.session_state[key] = []
                                elif key == "update_sel_week":
                                     st.session_state[key] = 1 # Or None if preferred start value
                                else:
                                     del st.session_state[key]
                        # Optionally uncomment rerun if you want the form truly blank after success
                        # st.rerun()

        elif cleared:
            # Explicitly clear all relevant session state keys for the form
            keys_to_clear = [
                "update_sel_country", "update_sel_center", "update_sel_batch",
                "update_sel_subject", "update_sel_faculty", "update_sel_chapters",
                "update_sel_week"
            ]
            for key in keys_to_clear:
                if key in st.session_state:
                     del st.session_state[key]
            st.info("Form cleared.")
            st.rerun() # Rerun to reflect cleared state

        elif home:
            st.session_state.page = "Home"
            st.rerun()


# --- Main App Logic ---
def main():
    """Main function to run the Streamlit application."""
    st.set_page_config(layout="wide") # Use wide layout

    # Initialize session state for page navigation
    if "page" not in st.session_state:
        st.session_state.page = "Home"

    # Get Google Sheets client and spreadsheet (cached)
    # Authorization happens here on first call
    client = get_gspread_client()
    spreadsheet = get_spreadsheet(client)

    # Page routing
    if st.session_state.page == "Home":
        show_home_page()
    elif st.session_state.page == "Admin":
        show_admin_page(spreadsheet)
    elif st.session_state.page == "Update":
        show_update_page(spreadsheet)
    else:
        st.session_state.page = "Home" # Default to home if state is invalid
        st.rerun()

if __name__ == "__main__":
    main()