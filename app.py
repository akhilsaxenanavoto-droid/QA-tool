import streamlit as st
import os
import time
import base64
import pandas as pd
import io
import re
import requests
from urllib.parse import urlparse
import plotly.express as px
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from groq import Groq
from dotenv import load_dotenv
from bs4 import BeautifulSoup

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

    /* THE SIMPLE PASTE & ATTACHMENT BOX */
    [data-testid="stFileUploader"] {
        min-height: 300px;
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

def to_excel_with_summary(df, report_type="QA Report"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Sheet 1: Detailed Data
        df.to_excel(writer, index=False, sheet_name='Detailed_Report')
        
        # Sheet 2: Summary Logic
        summary_data = {
            "Metric": ["Total Items Generated", "Report Date", "Tool Version"],
            "Value": [len(df), time.strftime("%Y-%m-%d %H:%M:%S"), "v2.0"]
        }
        
        # Add dynamic counts if columns exist
        for col in ['Severity', 'Priority', 'Status']:
            if col in df.columns:
                counts = df[col].value_counts()
                for val, count in counts.items():
                    summary_data["Metric"].append(f"{col}: {val}")
                    summary_data["Value"].append(count)
                    
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, index=False, sheet_name='Summary')
        
        # Formatting
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
    if os.path.exists("/usr/bin/chromedriver"):
        return webdriver.Chrome(service=Service("/usr/bin/chromedriver"), options=chrome_options)
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

def capture_screenshot(url):
    driver = None
    try:
        driver = init_driver()
        driver.get(url)
        time.sleep(4)
        filename = "temp_screenshot.png"
        driver.save_screenshot(filename)
        return filename
    except: return None
    finally:
        if driver: driver.quit()

def fetch_seo_detailed(driver, url):
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    try: status_code = requests.get(url, timeout=5).status_code
    except: status_code = "Error"
    meta_desc = soup.find("meta", attrs={"name": "description"})
    images = soup.find_all('img')
    h1s = [h1.get_text().strip() for h1 in soup.find_all('h1')]
    return {
        "Status": status_code,
        "Title": soup.title.string if soup.title else "MISSING",
        "Description": meta_desc.get("content", "MISSING") if meta_desc else "MISSING",
        "H1 Count": len(h1s),
        "Alt Issues": len([img for img in images if not img.get('alt')])
    }

def call_llm(prompt, image_path=None):
    current_key = os.environ.get("GROQ_API_KEY")
    if not current_key: return "Error: No API Key."
    client = Groq(api_key=current_key)
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
    if image_path:
        if isinstance(image_path, str):
            with open(image_path, "rb") as f:
                b64_img = base64.b64encode(f.read()).decode('utf-8')
        else:
            b64_img = base64.b64encode(image_path).decode('utf-8')
        messages[0]["content"].append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_img}"}})
    
    completion = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct", 
        messages=messages,
        temperature=0.1
    )
    return completion.choices[0].message.content

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
    try:
        st.image("Akhil.png", use_container_width=True)
    except:
        st.warning("⚠️ 'Akhil.png' not found.")
    
    st.title("Settings")
    env_key = os.getenv("GROQ_API_KEY", "")
    user_key = st.text_input("Groq API Key", value="", type="password")
    active_api_key = user_key if user_key else env_key
    if active_api_key:
        os.environ["GROQ_API_KEY"] = active_api_key
        st.success("🔒 API Key Active")
    
    st.markdown("---")
    st.subheader("📸 Image Input")
    st.write("Upload Full Image.")
    
    uploaded_file = st.file_uploader("", type=["png", "jpg", "jpeg"], key="main_input_box")
    
    if uploaded_file:
        st.markdown('<div class="preview-card">', unsafe_allow_html=True)
        st.image(uploaded_file, caption="Input Preview", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    categories = st.multiselect("Focus Areas:", ["UI/UX", "Functionality", "Security", "SEO", "Positive Testing", "Negative Testing", "Accessibility", "Functional", "Non-Functional", "Validation", "Usability"], default=["Functional", "Non-Functional", "Validation", "Usability"])
    num_cases = st.slider("Test Case Count", 5, 75, 30)
    custom_instructions = st.text_area("Custom Prompt Instructions")

# --- MAIN UI ---
st.markdown('<span class="akhil-highlight">Akhil</span> QA Tool', unsafe_allow_html=True)
url_input = st.text_input("Enter Website URL (Optional if image provided)", placeholder="https://example.com")

if not active_api_key: st.stop()

tab1, tab2, tab3 = st.tabs(["📝 Test Case Generator", "🐞 Bug Predictor", "📈 SEO Auditor"])

def get_processed_url():
    url = url_input.strip()
    if not url: return None
    if not url.startswith("http"): url = "https://" + url
    return url if is_valid_url(url) else None

def get_image_source(target_url):
    if uploaded_file is not None:
        return uploaded_file.getvalue(), False 
    elif target_url:
        path = capture_screenshot(target_url)
        return path, True 
    return None, False

# --- TAB 1: TEST CASES ---
with tab1:
    if st.button("🚀 Generate Test Cases", type="primary"):
        target = get_processed_url()
        img_data, is_path = get_image_source(target)
        if img_data:
            with st.spinner("Analyzing UI for Test Cases..."):
                prompt = f"Generate {num_cases} detailed test cases. Focus on {categories}. {custom_instructions}. Return ONLY a Markdown Table: Test Case ID, Category, Input, Test steps, Scenario, Pre-Condition, Expected Result, Actual Result, Browser, Screen, Status, Priority, Severity, Created By."
                res = call_llm(prompt, img_data)
                df = parse_markdown_table(res)
                if df is not None:
                    st.dataframe(df, use_container_width=True)
                    st.download_button("📥 Export QA Report", to_excel_with_summary(df), "QA_Test_Report.xlsx")
                else: st.write(res)
            if is_path and os.path.exists(img_data): os.remove(img_data)
        else: st.error("Please provide an image or URL.")

# --- TAB 2: BUG PREDICTOR ---
with tab2:
    if st.button("🕵️‍♂️ Predict Risks", type="primary"):
        target = get_processed_url()
        img_data, is_path = get_image_source(target)
        if img_data:
            with st.spinner("Analyzing UI for Bugs..."):
                prompt = f"Predict potential bugs. {custom_instructions}. Return ONLY a Markdown Table: Bug ID, Feature/Module, Risk Description, Potential Impact, Severity, Probability, Suggested Attack, Mitigation Strategy."
                res = call_llm(prompt, img_data)
                df_bugs = parse_markdown_table(res)
                if df_bugs is not None:
                    if 'Severity' in df_bugs.columns:
                        st.plotly_chart(px.pie(df_bugs, names='Severity', title='Severity Breakdown', hole=0.4), use_container_width=True)
                    st.dataframe(df_bugs, use_container_width=True)
                    st.download_button("📥 Export Bug Report", to_excel_with_summary(df_bugs), "Bug_Prediction_Report.xlsx")
                else: st.write(res)
            if is_path and os.path.exists(img_data): os.remove(img_data)
        else: st.error("Please provide an image or URL.")

# --- TAB 3: SEO AUDITOR ---
with tab3:
    if st.button("🔍 Run SEO Audit", type="primary"):
        target = get_processed_url()
        img_data, is_path = get_image_source(target)
        if img_data:
            with st.spinner("Analyzing SEO..."):
                seo_raw = {"Status": "Manual Upload", "H1 Count": "N/A", "Alt Issues": "N/A"}
                if target:
                    driver = init_driver()
                    try:
                        driver.get(target)
                        seo_raw = fetch_seo_detailed(driver, target)
                    finally: driver.quit()
                prompt = f"Perform SEO audit. Data: {seo_raw}. Return ONLY a Markdown Table: Audit Item, Finding, Impact, Current Status, Recommendation, Priority, Technical Difficulty."
                res = call_llm(prompt, img_data)
                df_seo = parse_markdown_table(res)
                if df_seo is not None:
                    k1, k2, k3 = st.columns(3)
                    k1.metric("Status", seo_raw["Status"])
                    k2.metric("H1 Count", seo_raw["H1 Count"])
                    k3.metric("Alt Issues", seo_raw["Alt Issues"])
                    st.dataframe(df_seo, use_container_width=True)
                    st.download_button("📥 Export SEO Audit", to_excel_with_summary(df_seo), "SEO_Audit_Report.xlsx")
                else: st.write(res)
            if is_path and os.path.exists(img_data): os.remove(img_data)
        else: st.error("Please provide an image or URL.")






