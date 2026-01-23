import streamlit as st
import os
import time
import pandas as pd
import io
import tempfile
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from PIL import Image

# Load environment variables
load_dotenv()

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Akhil QA Tool",
    page_icon="🕵️‍♂️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS STYLING ---
st.markdown("""
    <style>
    @media (min-width: 992px) {
        [data-testid="stSidebar"] { min-width: 400px !important; max-width: 500px !important; }
    }
    .akhil-highlight {
        font-weight: 900;
        background: linear-gradient(270deg, #FF4B2B, #FF416C, #9b59b6, #FF4B2B);
        background-size: 300% 300%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        animation: gradient-move 4s ease infinite;
        font-size: 4rem;
        display: inline-block;
    }
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        font-weight: bold;
        background-image: linear-gradient(to right, #FF4B2B 0%, #FF416C 51%, #FF4B2B 100%);
        background-size: 200% auto;
        color: white;
        border: none;
    }
    [data-testid="stFileUploaderDropzone"] {
        padding: 80px 10px;
        border: 3px dashed #FF416C !important;
        background-color: #fcfcfc;
        border-radius: 15px;
    }
    .preview-card {
        border: 2px solid #EEE;
        border-radius: 15px;
        padding: 10px;
        background: white;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---

def is_valid_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except: return False

def get_processed_url(url_input):
    url = url_input.strip()
    if not url: return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url if is_valid_url(url) else None

def to_excel_with_summary(df, report_type="QA Report"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Detailed_Report')
        summary_data = {
            "Metric": ["Total Items Generated", "Report Date", "Model Used"],
            "Value": [len(df), time.strftime("%Y-%m-%d %H:%M:%S"), "Gemini 1.5 Flash"]
        }
        for col in ['Severity', 'Priority', 'Status']:
            if col in df.columns:
                counts = df[col].value_counts()
                for val, count in counts.items():
                    summary_data["Metric"].append(f"{col}: {val}")
                    summary_data["Value"].append(count)
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, index=False, sheet_name='Summary')
        workbook = writer.book
        worksheet = writer.sheets['Summary']
        header_format = workbook.add_format({'bold': True, 'bg_color': '#FF416C', 'color': 'white'})
        for col_num, value in enumerate(summary_df.columns.values):
            worksheet.write(0, col_num, value, header_format)
    return output.getvalue()

def init_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-renderer-backgrounding")
    chrome_options.add_argument("--disable-background-timer-throttling")
    chrome_options.page_load_strategy = 'eager'

    # CLOUD FIX: Explicitly look for Chromium in Linux paths
    if os.path.exists("/usr/bin/chromium"):
        chrome_options.binary_location = "/usr/bin/chromium"
    elif os.path.exists("/usr/bin/chromium-browser"):
        chrome_options.binary_location = "/usr/bin/chromium-browser"

    try:
        return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    except Exception:
        # Fallback for Streamlit Cloud if Manager fails
        return webdriver.Chrome(options=chrome_options)

def capture_full_page_screenshot(url):
    driver = None
    try:
        driver = init_driver()
        driver.set_page_load_timeout(60)
        driver.get(url)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(2)

        width = driver.execute_script("return document.body.parentNode.scrollWidth")
        height = driver.execute_script("return document.body.parentNode.scrollHeight")
        driver.set_window_size(width, height) 
        time.sleep(3)
        
        filename = f"full_{int(time.time())}.png"
        driver.save_screenshot(filename)
        return filename
    finally:
        if driver: driver.quit()

# --- CLOUD FIX: Video Upload Helper ---
def upload_video_to_gemini(video_bytes, mime_type):
    # Create temp file in a way that works on Cloud
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
        tmp.write(video_bytes)
        tmp_path = tmp.name
    
    try:
        video_file = genai.upload_file(tmp_path, mime_type=mime_type)
        
        # Wait for Google to process the video (CRITICAL on Cloud)
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)
            
        if video_file.state.name == "FAILED":
            raise ValueError("Video processing failed by Google.")
            
        return video_file
    finally:
        # Cleanup temp file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def call_gemini(prompt, image_input=None, mime_type=None):
    api_key = st.session_state.get("gemini_api_key") or os.getenv("GEMINI_API_KEY")
    if not api_key: return "Error: No API Key."
    
    genai.configure(api_key=api_key)
    
    # Define the priority list of models
    # 1. Try Gemini 3 Flash Preview first (High performance)
    # 2. Fallback to Gemini 2.5 Flash (Stable/Backup)
    # 3. Final fallback to Gemini 1.5 Flash (Maximum reliability)
    models_to_try = [
        'gemini-3-flash-preview', 
        'gemini-2.5-flash',
        'gemini-2.5-flash-lite' 
    ]
    
    # CLOUD FIX: Disable Safety Filters to prevent "Empty Response" errors
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }
    
    # Prepare contents (Images/Video/Text)
    contents = []
    if image_input:
        if mime_type and "video" in mime_type:
            try:
                # Use the robust upload function
                video_file = upload_video_to_gemini(image_input, mime_type)
                contents.append(video_file)
            except Exception as e:
                return f"Video Error: {str(e)}"
        elif isinstance(image_input, str):
            with Image.open(image_input) as img:
                img_copy = img.copy()
            contents.append(img_copy)
        else:
            with Image.open(io.BytesIO(image_input)) as img:
                img_copy = img.copy()
            contents.append(img_copy)
    
    contents.append(prompt)
    
    # Loop through models until one works
    last_error = ""
    for model_name in models_to_try:
        try:
            # print(f"Attempting with model: {model_name}...") # Optional: Debug print
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(contents, safety_settings=safety_settings)
            
            # If successful, return immediately
            return response.text
            
        except Exception as e:
            # If this model fails, capture error and continue to the next model
            last_error = str(e)
            continue
            
    # If all models fail, return the error from the last attempt
    return f"Gemini Error (All models failed): {last_error}"

def parse_markdown_table(text):
    try:
        lines = [l for l in text.strip().split('\n') if '|' in l and '---' not in l]
        if len(lines) < 2: return None
        headers = [h.strip() for h in lines[0].strip('|').split('|')]
        data = [[c.strip() for c in l.strip('|').split('|')] for l in lines[1:]]
        return pd.DataFrame(data, columns=headers)
    except: return None

# --- SIDEBAR ---
with st.sidebar:
    try: st.image("Akhil.png", use_container_width=True)
    except: st.warning("⚠️ Logo 'Akhil.png' missing.")
    
    st.title("Settings")
    env_key = os.getenv("GEMINI_API_KEY", "")
    st.text_input("Google Gemini API Key", value=env_key, type="password", key="gemini_api_key")
    
    if st.session_state.get("gemini_api_key") or env_key:
        st.success("💎 Gemini Active")
    
    st.markdown("---")
    st.subheader("📸 Media Input")
    uploaded_file = st.file_uploader("", type=["png", "jpg", "jpeg", "mp4", "mov", "avi"], key="main_input_box")
    
    if uploaded_file:
        st.markdown('<div class="preview-card">', unsafe_allow_html=True)
        if "video" in uploaded_file.type:
            st.video(uploaded_file)
        else:
            st.image(uploaded_file, caption="Manual Upload Preview", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    categories = st.multiselect("Focus Areas:", ["UI/UX", "Functionality", "Validation", "Usability", "Security", "Positive Testing", "Negative Testing","Performance","SEO"], default=["UI/UX","Functionality","Positive Testing","Negative Testing"])
    num_cases = st.slider("Test Case Count", 5, 75, 50)
    custom_instructions = st.text_area("Custom Prompt Instructions")

# --- MAIN UI ---
st.markdown('<span class="akhil-highlight">Akhil</span> QA Engine', unsafe_allow_html=True)
url_input = st.text_input("Enter Website URL (Deep links supported)", placeholder="https://example.com/en/login")

tab1, tab2, tab3 = st.tabs(["📝 Test Case Generator", "🐞 Bug Predictor", "📈 SEO Auditor"])

def get_image_source(target_url):
    if uploaded_file is not None:
        return uploaded_file.getvalue(), False, uploaded_file.type 
    elif target_url:
        path = capture_full_page_screenshot(target_url)
        return path, True, "image/png" 
    return None, False, None

# # --- TAB 1: TEST CASES ---
with tab1:
    if st.button("🚀 Run Analysis", type="primary", key="btn_test"):
        url = get_processed_url(url_input)
        img_data, is_path, mime = get_image_source(url)
        
        if img_data:
            # 1. Create a placeholder at the TOP (Occupies full width)
            status_container = st.empty()
            
            # 2. Show the loading message inside the placeholder
            with status_container.container():
                st.info("Analysis in progress... AI is scanning the visual elements.")
                if mime and "video" in mime:
                    st.caption("⏳ Processing video frames... please wait.")
            
            # 3. Perform the analysis (The spinner will overlay comfortably)
            with st.spinner("Generating test scenarios..."):
                prompt = f"Senior QA: Analyze UI. Generate {num_cases} cases for {categories}. {custom_instructions}. Return ONLY Markdown Table: Test Case ID, Category, Input, Test steps, Scenario, Pre-Condition, Expected Result, Actual Result, Browser, Screen, Status, Priority, Severity, Created By."
                res = call_gemini(prompt, img_data, mime)
                df = parse_markdown_table(res)
            
            # 4. Clear the status message immediately
            status_container.empty()
            
            # 5. Display Results (Now fully Left-Aligned because there are no columns)
            if df is not None:
                st.subheader("Generated Test Cases")
                st.dataframe(df, use_container_width=True)
                st.download_button("📥 Export QA Report", to_excel_with_summary(df), "QA_Audit_Report.xlsx")
            else:
                st.markdown(res)
            
            # Cleanup
            if is_path and os.path.exists(img_data):
                time.sleep(1)
                os.remove(img_data)
        else:
            st.error("Capture failed. Verify URL or internet.")

# --- TAB 2: BUG PREDICTOR ---
with tab2:
    if st.button("🕵️‍♂️ Predict Risks", type="primary", key="btn_bug"):
        url = get_processed_url(url_input)
        img_data, is_path, mime = get_image_source(url)
        if img_data:
            col_info, col_data = st.columns([1, 3])
            with col_info:
                st.info("Scanning UI for bugs in background...")
            with col_data:
                st.subheader("Bug Predictions")
                with st.spinner("Finding risks..."):
                    prompt = f"Predict bugs. {custom_instructions}. Return ONLY Markdown Table: Bug ID, Feature, Risk Description, Severity, Probability, Mitigation Strategy."
                    res = call_gemini(prompt, img_data, mime)
                    df_bugs = parse_markdown_table(res)
                    if df_bugs is not None:
                        st.dataframe(df_bugs, use_container_width=True)
                        st.download_button("📥 Export Bug Report", to_excel_with_summary(df_bugs), "Bug_Report.xlsx")
                    else: st.markdown(res)
            if is_path and os.path.exists(img_data):
                time.sleep(1)
                os.remove(img_data)


# --- TAB 3: SEO AUDITOR ---
with tab3:
    if st.button("📈 Run SEO Audit", type="primary", key="btn_seo"):
        url = get_processed_url(url_input)
        img_data, is_path, mime = get_image_source(url)

        if img_data:
            # Create layout
            col_status, col_result = st.columns([1, 3])
            
            with col_status:
                st.info("🔍 Analyzing On-Page SEO...")
                st.caption("Checking Visual Hierarchy, Content Density, and UX Signals.")

            with col_result:
                st.subheader("SEO Audit Findings")
                
                with st.spinner("Evaluating SEO Factors..."):
                    # SEO Specific Prompt
                    prompt = (
                        f"Act as a Technical SEO Expert. Analyze this UI screenshot. "
                        f"Focus on: 1. Heading Hierarchy (H1/H2), 2. Content Readability & Density, "
                        f"3. CTA Placement, 4. Mobile Friendliness (Visual Layout), 5. Accessibility Risks (Contrast/Text Size). "
                        f"{custom_instructions}. "
                        f"Return ONLY a Markdown Table with these columns: "
                        f"Category, Observation, SEO Impact (High/Med/Low), Recommendation, Estimated Effort."
                    )
                    
                    # Call Gemini (uses the updated fallback function)
                    res = call_gemini(prompt, img_data, mime)
                    df_seo = parse_markdown_table(res)

                    if df_seo is not None:
                        # Display Data
                        st.dataframe(df_seo, use_container_width=True)
                        
                        # Visual Chart for Impact High/Med/Low
                        if 'SEO Impact' in df_seo.columns:
                            st.caption("Impact Distribution")
                            st.bar_chart(df_seo['SEO Impact'].value_counts())

                        # Export Button
                        st.download_button(
                            "📥 Export SEO Report", 
                            to_excel_with_summary(df_seo, "SEO Audit"), 
                            "SEO_Audit_Report.xlsx"
                        )
                    else:
                        # Fallback if table parsing fails
                        st.markdown(res)

            # Cleanup temporary screenshot
            if is_path and os.path.exists(img_data):
                time.sleep(1)
                os.remove(img_data)
        else:
            st.error("Input Error: Please provide a URL or upload an image.")




