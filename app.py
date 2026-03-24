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
import hashlib

st.set_page_config(page_title="FindSpares AI (Standalone)", layout="wide", initial_sidebar_state="collapsed")

# ---------------------------
# SESSION STATE INIT
# ---------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = None
if "auth_mode" not in st.session_state:
    st.session_state.auth_mode = "login"

# ---------------------------
# AUTH LOGIC
# ---------------------------
SALT = "FindSparesAI_2024"

def hash_pw(password):
    return hashlib.sha256((password + SALT).encode()).hexdigest()

def verify_user(username, password):
    try:
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0] == hash_pw(password):
            return True
    except:
        pass
    return False

def add_user(username, email, password):
    try:
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)", 
                       (username, email, hash_pw(password)))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False

# ---------------------------
# UI CUSTOMIZATION
# ---------------------------

with st.sidebar:
    st.title("FindSpares AI")
    if st.session_state.authenticated:
        st.success(f"👤 สวัสดีคุณ {st.session_state.username}")
        if st.button("🚪 Logout"):
            st.session_state.authenticated = False
            st.session_state.username = None
            st.rerun()
    
    st.divider()
    st.title("Settings")
    theme_mode = st.toggle("🌙 Night Mode", value=True)
    st.divider()
    st.markdown("FindSpares AI matches your requirements with local shop data using CLIP models.")

theme_css = f"""
<style>
@media (max-width: 640px) {{
    .main .block-container {{ padding: 1rem !important; }}
    h1 {{ font-size: 1.8rem !important; }}
}}
.stCard {{
    border-radius: 10px; padding: 15px; margin-bottom: 20px;
    border: 1px solid #ddd; transition: transform 0.2s;
}}
.stCard:hover {{
    transform: translateY(-5px); box-shadow: 0 4px 15px rgba(0,0,0,0.1);
}}
</style>
"""

if theme_mode:
    theme_css += """
<style>
.stApp { background-color: #0E1117; color: #FAFAFA; }
[data-testid="stHeader"] { background-color: rgba(14, 17, 23, 0.8); }
.stMarkdown, p, span, label { color: #FAFAFA !important; }
.stTextInput input, .stFileUploader section { background-color: #262730 !important; color: white !important; }
</style>
"""
else:
    theme_css += """
<style>
.stApp { background-color: #FFFFFF; color: #31333F; }
.stMarkdown, p, span, label { color: #31333F !important; }
</style>
"""

st.markdown(theme_css, unsafe_allow_html=True)

# ---------------------------
# AUTH SCREENS
# ---------------------------

def render_auth():
    st.markdown("<h1 style='text-align: center;'>🔐 ยินดีต้อนรับสู่ FindSpares AI</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        tab_login, tab_reg = st.tabs(["🔑 เข้าสู่ระบบ", "📝 ลงทะเบียน"])
        with tab_login:
            with st.form("login_form"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                if st.form_submit_button("Login", use_container_width=True):
                    if verify_user(u, p):
                        st.session_state.authenticated = True
                        st.session_state.username = u
                        st.rerun()
                    else:
                        st.error("❌ Username หรือ Password ไม่ถูกต้อง")
        with tab_reg:
            with st.form("reg_form"):
                u = st.text_input("Username")
                e = st.text_input("Email")
                p = st.text_input("Password", type="password")
                cp = st.text_input("Confirm Password", type="password")
                if st.form_submit_button("Register", use_container_width=True):
                    if p != cp:
                        st.error("❌ รหัสผ่านไม่ตรงกัน")
                    elif len(p) < 4:
                        st.error("❌ รหัสผ่านต้องมีอย่างน้อย 4 ตัวอักษร")
                    elif add_user(u, e, p):
                        st.success("✅ ลงทะเบียนสำเร็จ! กรุณาเข้าสู่ระบบ")
                    else:
                        st.error("❌ ผิดพลาด: Username นี้อาจถูกใช้ไปแล้ว")

# ---------------------------
# MAIN APP
# ---------------------------

def render_main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    @st.cache_resource
    def load_clip_model():
        model, preprocess = clip.load("ViT-B/32", device=device)
        return model, preprocess
    model, preprocess = load_clip_model()

    def get_db_connection():
        conn = sqlite3.connect("database.db")
        conn.row_factory = sqlite3.Row
        return conn

    @st.cache_resource
    def load_vectors_cached():
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT sp.id, sp.part_name, sp.image, s.shop_name, s.latitude, s.longitude, s.google_map_link, pe.embedding FROM part_embeddings pe JOIN shop_parts sp ON pe.part_id=sp.id JOIN shops s ON sp.shop_id=s.id")
        data = cursor.fetchall()
        conn.close()
        if not data: return None, []
        vectors, items = [], []
        for d in data:
            item_dict = dict(d)
            vec = np.array(json.loads(item_dict["embedding"])).astype("float32")
            vec = vec / np.linalg.norm(vec)
            vectors.append(vec); items.append(item_dict)
        vectors = np.array(vectors)
        idx = faiss.IndexFlatIP(vectors.shape[1]); idx.add(vectors)
        return idx, items

    with st.spinner("📦 กำลังโหลดข้อมูล..."):
        idx, items = load_vectors_cached()

    if idx is None:
        st.warning("⚠️ ไม่พบข้อมูลเวกเตอร์")
        st.stop()

    def encode_text(text):
        tokens = clip.tokenize([text]).to(device)
        with torch.no_grad(): vec = model.encode_text(tokens)
        vec = vec / vec.norm(dim=-1, keepdim=True)
        return vec.cpu().numpy().astype("float32")

    def encode_image(img):
        proc = preprocess(img).unsqueeze(0).to(device)
        with torch.no_grad(): vec = model.encode_image(proc)
        vec = vec / vec.norm(dim=-1, keepdim=True)
        return vec.cpu().numpy().astype("float32")

    def search_parts(q_vec, lat, lng, q_text=None):
        D, I = idx.search(q_vec, min(200, len(items)))
        results, seen = [], set()
        for score, i in zip(D[0], I[0]):
            if i == -1: continue
            item = items[i]
            if item["id"] in seen: continue
            seen.add(item["id"])
            R = 6371
            dlat, dlon = math.radians(item["latitude"]-lat), math.radians(item["longitude"]-lng)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(item["latitude"])) * math.sin(dlon/2)**2
            dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            results.append({
                "part_name": item["part_name"], "image": item["image"], "shop_name": item["shop_name"],
                "distance": dist, "score": float(max(0, min(1, score))), "map": item["google_map_link"]
            })
        if q_text:
            kw = q_text.lower()
            results = [r for r in results if kw in r["part_name"].lower()]
        return results

    st.title("🔧 FindSpares AI Search")
    st.info("📍 ระบบ Standalone Mode (SQLite)")

    tab_t, tab_u, tab_c = st.tabs(["🔍 ชื่ออะไหล่", "📁 อัปโหลดรูป", "📸 ถ่ายรูป"])
    with tab_t: q = st.text_input("ระบุคำค้นหา")
    with tab_u: up = st.file_uploader("เลือกไฟล์", type=["jpg","png","jpeg"])
    with tab_c: ci = st.camera_input("ถ่ายรูปอุปกรณ์")

    if "results" not in st.session_state: st.session_state.results = None
    if "page" not in st.session_state: st.session_state.page = 1

    if st.button("🚀 เริ่มการค้นหาด้วย AI", use_container_width=True):
        st.session_state.page = 1
        with st.spinner("🔎 กำลังประมวลผล..."):
            t_img = ci if ci else up
            if t_img:
                vec = encode_image(Image.open(t_img))
                res = search_parts(vec, 13.2839, 100.9289)
            elif q:
                vec = encode_text(q)
                res = search_parts(vec, 13.2839, 100.9289, q)
            else:
                st.warning("⚠️ กรุณาระบุข้อมูล"); st.stop()
            st.session_state.results = sorted(res, key=lambda x: (-x["score"], x["distance"]))

    if st.session_state.results:
        res = st.session_state.results
        total_p = math.ceil(len(res)/9)
        start = (st.session_state.page-1)*9
        page_res = res[start:start+9]
        cols = st.columns(3)
        for i, r in enumerate(page_res):
            with cols[i % 3]:
                with st.container(border=True):
                    path = f"shop_parts/{r['image']}"
                    if os.path.exists(path): st.image(path, use_container_width=True)
                    else: st.image("https://via.placeholder.com/300x200?text=No+Image", use_container_width=True)
                    st.subheader(r['part_name'])
                    st.write(f"🏪 {r['shop_name']}"); st.write(f"📍 {r['distance']:.2f} กม.")
                    st.progress(r["score"], text=f"Match: {int(r['score']*100)}%")
                    st.link_button("🗺️ แผนที่", r['map'], use_container_width=True)
        if total_p > 1:
            pc1, pc2, pc3 = st.columns([1, 2, 1])
            with pc1:
                if st.button("⬅️ ก่อนหน้า") and st.session_state.page > 1:
                    st.session_state.page -= 1; st.rerun()
            with pc2: st.write(f"หน้า {st.session_state.page}/{total_p}")
            with pc3:
                if st.button("ถัดไป ➡️") and st.session_state.page < total_p:
                    st.session_state.page += 1; st.rerun()

if not st.session_state.authenticated:
    render_auth()
else:
    render_main()