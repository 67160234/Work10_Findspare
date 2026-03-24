import streamlit as st
import sqlite3
import torch
import clip
import numpy as np
import json
from PIL import Image
import faiss
import math
import os

st.set_page_config(page_title="FindSpares AI (Standalone)", layout="wide", initial_sidebar_state="collapsed")

# ---------------------------
# UI CUSTOMIZATION (Theme & Mobile)
# ---------------------------

# Theme Toggle in Sidebar
with st.sidebar:
    st.title("Settings")
    theme_mode = st.toggle("🌙 Night Mode", value=True)
    st.divider()
    st.markdown("""
    ### About
    FindSpares AI matches your requirements with local shop data using CLIP models.
    """)

# Inject Custom CSS for Theme and Responsiveness
theme_css = """
<style>
    /* Mobile Responsive Optimizations */
    @media (max-width: 640px) {
        .main .block-container {
            padding: 1rem !important;
        }
        h1 {
            font-size: 1.8rem !important;
        }
    }

    /* Card Styling */
    .stCard {
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 20px;
        border: 1px solid #ddd;
        transition: transform 0.2s;
    }
    .stCard:hover {
        transform: translateY(-5px);
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
</style>
"""

# Dynamic Theme Override
if theme_mode:
    # 🌙 Dark Mode Override
    theme_css += """
    <style>
        .stApp {
            background-color: #0E1117;
            color: #FAFAFA;
        }
        [data-testid="stHeader"] {
            background-color: rgba(14, 17, 23, 0.8);
        }
        .stMarkdown, p, span, label {
            color: #FAFAFA !important;
        }
        .stTextInput input, .stFileUploader section {
            background-color: #262730 !important;
            color: white !important;
        }
    </style>
    """
else:
    # ☀️ Light Mode Override
    theme_css += """
    <style>
        .stApp {
            background-color: #FFFFFF;
            color: #31333F;
        }
        .stMarkdown, p, span, label {
            color: #31333F !important;
        }
    </style>
    """

st.markdown(theme_css, unsafe_allow_html=True)

# ---------------------------
# LOAD MODEL (Cached)
# ---------------------------

device = "cuda" if torch.cuda.is_available() else "cpu"

@st.cache_resource
def load_clip_model():
    model, preprocess = clip.load("ViT-B/32", device=device)
    return model, preprocess

model, preprocess = load_clip_model()

# ---------------------------
# DATABASE (SQLite - Standalone Mode)
# ---------------------------

DB_PATH = "database.db"

def get_db_connection():
    if not os.path.exists(DB_PATH):
        st.error(f"❌ ไม่พบไฟล์ฐานข้อมูล '{DB_PATH}'! กรุณารันสคริปต์ convert_to_sqlite.py และอัปโหลดไฟล์ไปที่ GitHub")
        st.stop()
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # ให้คืนค่าเป็น Dict-like
    return conn

# ---------------------------
# LOAD VECTORS (Cached)
# ---------------------------

@st.cache_resource
def load_vectors_cached():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT 
        sp.id, 
        sp.part_name, 
        sp.image, 
        s.shop_name, 
        s.latitude, 
        s.longitude, 
        s.google_map_link,
        pe.embedding
    FROM part_embeddings pe
    JOIN shop_parts sp ON pe.part_id=sp.id
    JOIN shops s ON sp.shop_id=s.id
    """)

    data = cursor.fetchall()
    conn.close()

    if not data:
        return None, []

    vectors = []
    items = []

    for d in data:
        # SQLite Row behaves like a dict row[key]
        item_dict = dict(d)
        vec = np.array(json.loads(item_dict["embedding"])).astype("float32")
        vec = vec / np.linalg.norm(vec)
        vectors.append(vec)
        items.append(item_dict)

    vectors = np.array(vectors)
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    return index, items

# Initialize Index
with st.spinner("📦 กำลังโหลดข้อมูลจากไฟล์ฐานข้อมูล..."):
    index, items = load_vectors_cached()

if index is None:
    st.warning("⚠️ ไม่พบข้อมูลเวกเตอร์ในฐานข้อมูล")
    st.stop()

# ---------------------------
# DISTANCE & TRANSLATE
# ---------------------------

def distance(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2-lat1)
    dlon = math.radians(lon2-lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R*c

def translate_keyword(keyword):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT part_name 
    FROM part_synonyms 
    WHERE synonym LIKE ?
    """, ("%"+keyword+"%",))
    r = cursor.fetchone()
    conn.close()
    if r:
        return r["part_name"]
    return keyword

# ---------------------------
# SEARCH & AI
# ---------------------------

def encode_text(text):
    text_tokens = clip.tokenize([text]).to(device)
    with torch.no_grad():
        vec = model.encode_text(text_tokens)
    vec = vec / vec.norm(dim=-1, keepdim=True)
    return vec.cpu().numpy().astype("float32")

def encode_image(img):
    img_processed = preprocess(img).unsqueeze(0).to(device)
    with torch.no_grad():
        vec = model.encode_image(img_processed)
    vec = vec / vec.norm(dim=-1, keepdim=True)
    return vec.cpu().numpy().astype("float32")

def search(query_vec, user_lat, user_lng, query=None):
    D, I = index.search(query_vec, min(200, len(items)))
    results = []
    seen = set()

    for score, i in zip(D[0], I[0]):
        if i == -1: continue # Handle FAISS index empty results
        item = items[i]
        key = item["id"]
        if key in seen:
            continue
        seen.add(key)

        dist = distance(user_lat, user_lng, item["latitude"], item["longitude"])
        score = float(score)
        score = max(0, min(1, score))

        results.append({
            "part_name": item["part_name"],
            "image": item["image"],
            "shop_name": item["shop_name"],
            "distance": dist,
            "score": score,
            "map": item["google_map_link"]
        })

    if query:
        keyword = query.lower()
        results = [r for r in results if keyword in r["part_name"].lower()]

    return results

# ---------------------------
# UI
# ---------------------------

st.title("🔧 FindSpares AI (Standalone)")

user_lat = 13.2839215
user_lng = 100.9289055

st.info("📍 ระบบรันแบบ Standalone (ดาวน์โหลดข้อมูลมาไว้ในไฟล์ database.db)")

col1, col2 = st.columns(2)

with col1:
    query = st.text_input("ค้นหาอะไหล่ (ระบุคำค้นหา)")

with col2:
    upload = st.file_uploader("หรืออัปโหลดรูปภาพเพื่อค้นหา")

if "results" not in st.session_state:
    st.session_state.results = None

if "page" not in st.session_state:
    st.session_state.page = 1

per_page = 9

if st.button("🚀 ค้นหาด้วย AI"):
    st.session_state.page = 1
    with st.spinner("🔎 กำลังประมวลผลการค้นหา..."):
        if upload:
            img = Image.open(upload)
            query_vec = encode_image(img)
            query_text = None
        else:
            query_text = translate_keyword(query)
            query_vec = encode_text(query_text)

        results = search(query_vec, user_lat, user_lng, query_text)
        results = sorted(results, key=lambda x: (-x["score"], x["distance"]))
        st.session_state.results = results

# ---------------------------
# DISPLAY RESULTS
# ---------------------------

if st.session_state.results:
    results = st.session_state.results
    page = st.session_state.page
    total_pages = math.ceil(len(results) / per_page)
    
    start = (page - 1) * per_page
    end = start + per_page
    page_results = results[start:end]

    # Result Grid (Adaptive)
    # On mobile, Streamlit automatically stacks columns. 
    # We use a loop that works well with the automatic stacking.
    
    # Use 1 column for very small, 2 for medium, 3 for large? 
    # Streamlit standard columns are best for this.
    cols = st.columns(3)
    for i, r in enumerate(page_results):
        with cols[i % 3]:
            # Custom Container for Card
            with st.container(border=True):
                img_path = f"shop_parts/{r['image']}"
                if os.path.exists(img_path):
                    st.image(img_path, use_container_width=True)
                else:
                    st.image("https://via.placeholder.com/300x200?text=No+Image", use_container_width=True)
                
                st.subheader(f"{r['part_name']}")
                st.write(f"🏪 **ร้าน:** {r['shop_name']}")
                st.write(f"📍 **ระยะห่าง:** {r['distance']:.2f} กม.")
                
                # Match Progress Bar or Metric
                st.progress(r["score"], text=f"AI Match: {int(r['score']*100)}%")
                
                st.link_button("🗺️ ดูแผนที่ร้าน", r['map'], use_container_width=True)

    if total_pages > 1:
        p_col1, p_col2, p_col3 = st.columns([1, 2, 1])
        with p_col1:
            if st.button("⬅️ ก่อนหน้า") and page > 1:
                st.session_state.page -= 1
                st.rerun()
        with p_col2:
            st.write(f"หน้า {page} จาก {total_pages}")
        with p_col3:
            if st.button("ถัดไป ➡️") and page < total_pages:
                st.session_state.page += 1
                st.rerun()