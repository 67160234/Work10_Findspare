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
if "user_id" not in st.session_state:
    st.session_state.user_id = None

# ---------------------------
# AUTH & DB LOGIC
# ---------------------------
SALT = "FindSparesAI_2024"

def get_db_connection():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def hash_pw(password):
    return hashlib.sha256((password + SALT).encode()).hexdigest()

def verify_user(username, password):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Fail-safe: Ensure users table exists
        cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, email TEXT, password TEXT)")
        
        cursor.execute("SELECT id, password FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()
        if row and row["password"] == hash_pw(password):
            return row["id"]
    except Exception as e:
        st.error(f"❌ ระบบยืนยันตัวตนผิดพลาด: {e}")
    return None

def add_user(username, email, password):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Fail-safe: Ensure users table exists
        cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, email TEXT, password TEXT)")
        
        cursor.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)", 
                       (username, email, hash_pw(password)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            st.warning("⚠️ มีชื่อผู้ใช้นี้อยู่ในระบบแล้ว")
        else:
            st.error(f"❌ ไม่สามารถบันทึกข้อมูลได้: {e}")
        return False

# ---------------------------
# FAVORITES LOGIC
# ---------------------------
def toggle_favorite(user_id, part_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Ensure table exists (fail-safe)
        cursor.execute("CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, part_id INTEGER, UNIQUE(user_id, part_id))")
        
        cursor.execute("SELECT id FROM favorites WHERE user_id = ? AND part_id = ?", (user_id, part_id))
        if cursor.fetchone():
            cursor.execute("DELETE FROM favorites WHERE user_id = ? AND part_id = ?", (user_id, part_id))
            st.toast("🗑️ ลบจากรายการโปรดแล้ว")
        else:
            cursor.execute("INSERT INTO favorites (user_id, part_id) VALUES (?, ?)", (user_id, part_id))
            st.toast("⭐ บันทึกเป็นรายการโปรดแล้ว")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาดในระบบฐานข้อมูล: {e}")
        return False

def get_user_favorites(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, part_id INTEGER, UNIQUE(user_id, part_id))")
        cursor.execute("SELECT part_id FROM favorites WHERE user_id = ?", (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [r["part_id"] for r in rows]
    except:
        return []

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
            st.session_state.user_id = None
            st.rerun()
    st.title("Settings")
    theme_mode = st.toggle("🌙 Night Mode", value=True)
    
    # --- NEW: Developer Tools (For Debugging) ---
    st.divider()
    with st.expander("🛠️ Developer Tools (Debug DB)"):
        st.write("ตรวจสอบข้อมูลในฐานข้อมูล (เฉพาะแอดมิน/คนพัฒนา)")
        db_tables = ["users", "favorites", "shops", "shop_parts"]
        selected_table = st.selectbox("เลือกตารางเพื่อดูข้อมูล", db_tables)
        
        if st.button("👁️ ดึงข้อมูลตาราง", use_container_width=True):
            try:
                conn = get_db_connection()
                # Create table if missing during debug check
                if selected_table == "users":
                    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, email TEXT, password TEXT)")
                elif selected_table == "favorites":
                    conn.execute("CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, part_id INTEGER, UNIQUE(user_id, part_id))")
                
                df = st.dataframe(conn.execute(f"SELECT * FROM {selected_table} LIMIT 100").fetchall())
                conn.close()
            except Exception as e:
                st.error(f"⚠️ ไม่สามารถเรียกดูข้อมูลได้: {e}")
    
    st.divider()
    st.markdown("FindSpares AI matches your requirements with local shop data using CLIP models.")

theme_css = f"""
<style>
@media (max-width: 640px) {{
    .main .block-container {{ padding: 1rem !important; }}
    h1 {{ font-size: 1.8rem !important; }}
}}
.stCard {{
    border-radius: 12px; padding: 15px; margin-bottom: 20px;
    border: 1px solid #1E3A8A; transition: transform 0.2s;
    background-color: rgba(30, 58, 138, 0.05);
}}
.stCard:hover {{
    transform: translateY(-5px); box-shadow: 0 4px 15px rgba(251, 191, 36, 0.3);
}}
/* Custom Button Style */
div.stButton > button {{
    background-color: #1E3A8A !important;
    color: #FBBF24 !important;
    border: 1px solid #FBBF24 !important;
    border-radius: 8px !important;
}}
div.stButton > button:hover {{
    background-color: #FBBF24 !important;
    color: #1E3A8A !important;
}}
/* Link Button Style */
div.stLinkButton > a {{
    background-color: #FBBF24 !important;
    color: #1E3A8A !important;
    border-radius: 8px !important;
    font-weight: bold !important;
}}
</style>
"""
if theme_mode:
    theme_css += """
<style>
.stApp { background-color: #0F172A; color: #F1F5F9; }
[data-testid="stHeader"] { background-color: rgba(15, 23, 42, 0.9); }
h1, h2, h3, p, span, label { color: #F1F5F9 !important; }
.stTextInput input, .stFileUploader section { background-color: #1E293B !important; color: white !important; border: 1px solid #1E3A8A !important; }
/* Progress Bar Yellow */
.stProgress > div > div > div > div { background-color: #FBBF24 !important; }
</style>
"""
else:
    theme_css += """
<style>
.stApp { background-color: #F8FAFC; color: #1E293B !important; }
h1, h2, h3, p, span, label, div, .stMarkdown { color: #1E293B !important; }
.stProgress > div > div > div > div { background-color: #1E3A8A !important; }
</style>
"""
st.markdown(theme_css, unsafe_allow_html=True)

# ---------------------------
# SCREENS
# ---------------------------
def render_auth():
    st.markdown("<h1 style='text-align: center;'>🔐 ยินดีต้อนรับสู่ FindSpares AI</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        tab_login, tab_reg = st.tabs(["🔑 เข้าสู่ระบบ", "📝 ลงทะเบียน"])
        with tab_login:
            with st.form("login"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                if st.form_submit_button("Login", use_container_width=True):
                    uid = verify_user(u, p)
                    if uid:
                        st.session_state.authenticated = True
                        st.session_state.username = u
                        st.session_state.user_id = uid
                        st.rerun()
                    else: st.error("❌ Username หรือ Password ไม่ถูกต้อง")
        with tab_reg:
            with st.form("reg"):
                u = st.text_input("Username"); e = st.text_input("Email")
                p = st.text_input("Password", type="password"); cp = st.text_input("Confirm Password", type="password")
                if st.form_submit_button("Register", use_container_width=True):
                    if p != cp: st.error("❌ รหัสผ่านไม่ตรงกัน")
                    elif len(p) < 4: st.error("❌ รหัสผ่านสั้นเกินไป")
                    elif add_user(u, e, p): st.success("✅ สำเร็จ! กรุณาเข้าสู่ระบบ")
                    else: st.error("❌ Username ถูกใช้ไปแล้ว")

def render_main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    @st.cache_resource
    def load_clip_model():
        model, preprocess = clip.load("ViT-B/32", device=device)
        return model, preprocess
    model, preprocess = load_clip_model()

    @st.cache_resource
    def load_vectors_cached():
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT sp.id, sp.part_name, sp.image, s.shop_name, s.latitude, s.longitude, s.google_map_link, pe.embedding FROM part_embeddings pe JOIN shop_parts sp ON pe.part_id=sp.id JOIN shops s ON sp.shop_id=s.id")
        data = cursor.fetchall(); conn.close()
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
                "id": item["id"], "part_name": item["part_name"], "image": item["image"], "shop_name": item["shop_name"],
                "distance": dist, "score": float(max(0, min(1, score))), "map": item["google_map_link"]
            })
        if q_text:
            kw = q_text.lower()
            results = [r for r in results if kw in r["part_name"].lower()]
        return results

    st.title("🔧 FindSpares AI Search")
    
    # NEW: My Favorites Tab
    tab_search, tab_fav = st.tabs(["🔍 ค้นหาอะไหล่", "⭐ รายการโปรด"])
    
    with tab_search:
        st.info("📍 ค้นหาด้วยชื่อ หรือ อัปโหลด/ถ่ายรูป")
        t1, t2, t3 = st.tabs(["🔍 ชื่อ", "📁 ไฟล์", "📸 กล้อง"])
        with t1: q = st.text_input("ระบุคำค้นหา")
        with t2: up = st.file_uploader("เลือกไฟล์", type=["jpg","png","jpeg"])
        with t3: ci = st.camera_input("ถ่ายรูป")
        
        if st.button("🚀 เริ่มการค้นหา", use_container_width=True):
            with st.spinner("🔎 กำลังประมวลผล..."):
                t_img = ci if ci else up
                if t_img: res = search_parts(encode_image(Image.open(t_img)), 13.2839, 100.9289)
                elif q: res = search_parts(encode_text(q), 13.2839, 100.9289, q)
                else: st.warning("⚠️ ระบุข้อมูลก่อน"); st.stop()
                st.session_state.results = sorted(res, key=lambda x: (-x["score"], x["distance"]))
                st.session_state.page = 1

        if st.session_state.get("results"):
            render_grid(st.session_state.results)

    with tab_fav:
        fav_ids = get_user_favorites(st.session_state.user_id)
        if not fav_ids:
            st.info("คุณยังไม่มีรายการโปรด ดาวอะไหล่ที่สนใจตอนนี้เลย!")
        else:
            fav_items = [item for item in items if item["id"] in fav_ids]
            # Convert items to result format
            res = []
            for item in fav_items:
                res.append({
                    "id": item["id"], "part_name": item["part_name"], "image": item["image"], "shop_name": item["shop_name"],
                    "distance": 0, "score": 1.0, "map": item["google_map_link"]
                })
            render_grid(res, is_fav_view=True)

def render_grid(results, is_fav_view=False):
    per_page = 9
    total_p = math.ceil(len(results)/per_page)
    page = st.session_state.get("page", 1)
    page_res = results[(page-1)*per_page : page*per_page]
    
    fav_ids = get_user_favorites(st.session_state.user_id)
    
    cols = st.columns(3)
    for i, r in enumerate(page_res):
        with cols[i % 3]:
            with st.container(border=True):
                path = f"shop_parts/{r['image']}"
                if os.path.exists(path): st.image(path, use_container_width=True)
                else: st.image("https://via.placeholder.com/300x200?text=No+Image", use_container_width=True)
                
                # Header with Star Toggle
                h1, h2 = st.columns([4, 1])
                with h1: st.subheader(r['part_name'])
                with h2:
                    star_icon = "⭐" if r["id"] in fav_ids else "☆"
                    if st.button(star_icon, key=f"fav_{r['id']}_{'v' if is_fav_view else 's'}"):
                        toggle_favorite(st.session_state.user_id, r["id"])
                        st.rerun()
                
                st.write(f"🏪 {r['shop_name']}")
                if not is_fav_view:
                    st.write(f"📍 {r['distance']:.2f} กม.")
                    st.progress(r["score"], text=f"Match: {int(r['score']*100)}%")
                st.link_button("🗺️ แผนที่", r['map'], use_container_width=True)

    if total_p > 1:
        pc1, pc2, pc3 = st.columns([1, 2, 1])
        with pc1:
            if st.button("⬅️ ก่อนหน้า", key="prev") and page > 1:
                st.session_state.page -= 1; st.rerun()
        with pc2: st.write(f"หน้า {page}/{total_p}")
        with pc3:
            if st.button("ถัดไป ➡️", key="next") and page < total_p:
                st.session_state.page += 1; st.rerun()

if not st.session_state.authenticated: render_auth()
else: render_main()