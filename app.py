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
    </style>
""", unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---

def is_valid_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='QA_Report')
    return output.getvalue()

def init_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    
    # Path for Streamlit Cloud
    if os.path.exists("/usr/bin/chromedriver"):
        return webdriver.Chrome(
            service=Service("/usr/bin/chromedriver"), 
            options=chrome_options
        )
    
    # Path for your local computer (Automatic fallback)
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), 
        options=chrome_options
    )

def capture_screenshot(url):
    driver = None
    try:
        driver = init_driver()
        driver.get(url)
        time.sleep(4)
        filename = "temp_screenshot.png"
        driver.save_screenshot(filename)
        return filename
    except:
        return None
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
        with open(image_path, "rb") as f:
            b64_img = base64.b64encode(f.read()).decode('utf-8')
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
    # RE-ADD LOGO
    try:
        st.image("Akhil.png", use_container_width=True)
    except:
        st.warning("⚠️ 'Akhil.png' not found.")
    
    st.title("Settings")
    env_key = os.getenv("GROQ_API_KEY", "")
    user_key = st.text_input("Groq API Key", value="", type="password", placeholder="Using .env key..." if env_key else "Enter key...")
    active_api_key = user_key if user_key else env_key
    if active_api_key:
        os.environ["GROQ_API_KEY"] = active_api_key
        st.success("🔒 API Key Active")
    
    st.markdown("---")
    categories = st.multiselect("Focus Areas:", ["UI/UX", "Functionality", "Security", "SEO", "Performance", "Positive Testing", "Negative Testing"], default=["UI/UX", "Functionality"])
    num_cases = st.slider("Test Case Count", 5,75,20)
    
    # RE-ADD CUSTOM PROMPT OPTION
    st.markdown("---")
    st.subheader("🤖 AI Tuning")
    custom_instructions = st.text_area("Custom Prompt Instructions", placeholder="e.g. Focus on financial compliance or mobile responsiveness...")

# --- MAIN UI ---
st.markdown('<span class="akhil-highlight">Akhil</span> QA Tool', unsafe_allow_html=True)
url_input = st.text_input("Enter Website URL", placeholder="https://example.com")

if not active_api_key: st.stop()

tab1, tab2, tab3 = st.tabs(["📝 Test Case Generator", "🐞 Bug Predictor", "📈 SEO Auditor"])

def get_processed_url():
    url = url_input.strip()
    if not url: return None
    if not url.startswith("http"): url = "https://" + url
    return url if is_valid_url(url) else None

# --- TAB 1: TEST CASES ---
with tab1:
    if st.button("🚀 Generate Test Cases", type="primary"):
        target = get_processed_url()
        if target:
            img = capture_screenshot(target)
            if img:
                with st.spinner("Generating Tests..."):
                    prompt = f"Generate {num_cases} test cases for {target}. Focus on {categories}. {custom_instructions}. Return ONLY a Markdown Table: Test Case ID, Category, Scenario, Pre-Condition, Expected Result, Screen, Status, Priority, Severity, Created By."
                    res = call_llm(prompt, img)
                    df = parse_markdown_table(res)
                    if df is not None:
                        st.dataframe(df, use_container_width=True)
                        c1, c2 = st.columns(2)
                        c1.download_button("📥 CSV", df.to_csv(index=False), "tests.csv")
                        c2.download_button("📊 Excel", to_excel(df), "tests.xlsx")
                    else: st.write(res)
                if os.path.exists(img): os.remove(img)

# --- TAB 2: BUG PREDICTOR ---
with tab2:
    if st.button("🕵️‍♂️ Predict Risks", type="primary"):
        target = get_processed_url()
        if target:
            img = capture_screenshot(target)
            if img:
                with st.spinner("Analyzing Risks..."):
                    prompt = f"Predict potential bugs for {target}. {custom_instructions}. Return ONLY a Markdown Table: Feature, Risk, Severity, Suggested Attack."
                    res = call_llm(prompt, img)
                    df_bugs = parse_markdown_table(res)
                    if df_bugs is not None:
                        # RESTORE CHART UI
                        st.subheader("📊 Risk Distribution Analysis")
                        if 'Severity' in df_bugs.columns:
                            fig = px.pie(df_bugs, names='Severity', title='Risk Severity Breakdown', 
                                         hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
                            st.plotly_chart(fig, use_container_width=True)
                        
                        st.subheader("📋 Predicted Bug Registry")
                        st.dataframe(df_bugs, use_container_width=True)
                        
                        c1, c2 = st.columns(2)
                        c1.download_button("📥 CSV Report", df_bugs.to_csv(index=False), "bug_risks.csv")
                        c2.download_button("📊 Excel Report", to_excel(df_bugs), "bug_risks.xlsx")
                    else: st.write(res)
                if os.path.exists(img): os.remove(img)

# --- TAB 3: SEO AUDITOR ---
with tab3:
    if st.button("🔍 Run Detailed SEO Audit", type="primary"):
        target = get_processed_url()
        if target:
            with st.spinner("Detailed SEO Scrape..."):
                driver = init_driver()
                try:
                    driver.get(target)
                    seo_raw = fetch_seo_detailed(driver, target)
                    prompt = f"Detailed SEO Audit for {target}. Data: {seo_raw}. {custom_instructions}. Return a Markdown Table: Category, Finding, Status, Suggestion, Priority."
                    res = call_llm(prompt)
                    df_seo = parse_markdown_table(res)
                    if df_seo is not None:
                        st.subheader("🚀 SEO KPIs")
                        k1, k2, k3 = st.columns(3)
                        k1.metric("Status", seo_raw["Status"])
                        k2.metric("H1 Count", seo_raw["H1 Count"])
                        k3.metric("Alt Issues", seo_raw["Alt Issues"])
                        
                        st.dataframe(df_seo, use_container_width=True)
                        c1, c2 = st.columns(2)
                        c1.download_button("📥 CSV", df_seo.to_csv(index=False), "seo_audit.csv")
                        c2.download_button("📊 Excel", to_excel(df_seo), "seo_audit.xlsx")
                    else: st.write(res)
                finally: driver.quit()








