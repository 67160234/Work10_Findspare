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

from supabase import create_client, Client

st.set_page_config(page_title="FindSpares AI (Cloud)", layout="wide", initial_sidebar_state="collapsed")

# ---------------------------
# SESSION STATE INIT (MUST BE AT TOP)
# ---------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = None
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "page" not in st.session_state:
    st.session_state.page = 1
if "show_camera" not in st.session_state:
    st.session_state.show_camera = False

# ---------------------------
# SEARCH SYNONYMS (SMART SEARCH)
# ---------------------------
SYNONYM_MAP = {
    "Brake Pad": ["เบรก", "เบรค", "ผ้าเบรก", "ผ้าเบรค", "ก้ามเบรก", "เบรกหน้า", "เบรกหลัง", "Brake Pad", "Brake Pads", "Brakepads"],
    "Car Battery": ["แบตเตอรี่", "แบต", "แบตรถยนต์", "ไฟฟ้ารถ", "ขั้วแบต", "น้ำกลั่น", "Car Battery", "Battery", "Accu", "Car Batt"],
    "Air Filter": ["กรองอากาศ", "กรองเครื่อง", "กรอง", "ไส้กรอง", "กรองฝุ่น", "กรองแอร์", "Air Filter", "Air Filters", "Filter", "Air Filter Element"],
    "Ball Joint": ["ลูกหมาก", "ลูกหมากปีกนก", "ลูกหมากแร็ค", "ช่วงล่าง", "ลูกหมากล่าง", "ลูกหมากบน", "คันชัก", "Ball Joint", "Ball Joints", "Suspension Joint"],
    "Brake Disc": ["จานเบรก", "จานเบรค", "จาน", "จานดิส", "เบรกจาน", "จานดิสก์", "Brake Disc", "Brake Discs", "Disc Brake", "Rotor"],
    "Radiator": ["หม้อน้ำ", "ระบายความร้อน", "พัดลมหม้อน้ำ", "ฝาหม้อน้ำ", "ท่อน้ำ", "รังผึ้งหม้อน้ำ", "น้ำยาหล่อเย็น", "Radiator", "Radiators", "Cooling System"],
    "Shock Absorber": ["โช้ค", "โช๊ค", "โช้คอัพ", "สปริง", "ช่วงล่าง", "Shock Absorber", "Shock Absorbers", "Shock", "Shocks", "Strut", "Struts"],
    "Spark Plug": ["หัวเทียน", "คอยล์จุดระเบิด", "จุดระเบิด", "ไฟแปลบ", "หัวเทียนเข็ม", "หัวเทียนรถ", "Spark Plug", "Spark Plugs", "Plug", "Ignition Plug"],
    "Starter Motor": ["ไดสตาร์ท", "มอเตอร์สตาร์ท", "สตาร์ทรถ", "ไดสตาร์ทรถ", "มอเตอร์สตาร์ทรถ", "Starter Motor", "Starter", "Starters", "Ignition Starter"],
    "AC Compressor": ["คอมแอร์", "คอมเพรสเซอร์", "แอร์รถยนต์", "ทำความเย็น", "น้ำยาแอร์", "ท่อแอร์", "AC Compressor", "Compressor", "Air Con", "AC Unit"]
}

# ---------------------------
# DATABASE CONFIG (SUPABASE FALLBACK TO SQLITE)
# ---------------------------
SUPABASE_URL = st.secrets.get("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)

if USE_SUPABASE:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    st.sidebar.warning("💾 Using local SQLite (Session only). Use Supabase for permanent storage.")

SALT = "FindSparesAI_2024"

def get_db_connection():
    # Only for SQLite fallback
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def hash_pw(password):
    return hashlib.sha256((password + SALT).encode()).hexdigest()

def verify_user(username, password):
    try:
        pw_hash = hash_pw(password)
        if USE_SUPABASE:
            res = supabase.table("users").select("id").eq("username", username).eq("password", pw_hash).execute()
            if res.data: return res.data[0]["id"]
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, email TEXT, password TEXT)")
            cursor.execute("SELECT id FROM users WHERE username = ? AND password = ?", (username, pw_hash))
            row = cursor.fetchone()
            conn.close()
            if row: return row["id"]
    except Exception as e:
        st.error(f"❌ ระบบยืนยันตัวตนผิดพลาด: {e}")
    return None

def add_user(username, email, password):
    try:
        pw_hash = hash_pw(password)
        if USE_SUPABASE:
            res = supabase.table("users").insert({"username": username, "email": email, "password": pw_hash}).execute()
            return True
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, email TEXT, password TEXT)")
            cursor.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)", (username, email, pw_hash))
            conn.commit(); conn.close()
            return True
    except Exception as e:
        if "UNIQUE" in str(e) or "duplicate" in str(e).lower():
            st.warning("⚠️ มีชื่อผู้ใช้นี้อยู่ในระบบแล้ว")
        else:
            st.error(f"❌ ไม่สามารถบันทึกข้อมูลได้: {e}")
        return False

# ---------------------------
# FAVORITES LOGIC
# ---------------------------
def toggle_favorite(user_id, part_id):
    try:
        if USE_SUPABASE:
            # Check exist
            check = supabase.table("favorites").select("id").eq("user_id", user_id).eq("part_id", part_id).execute()
            if check.data:
                supabase.table("favorites").delete().eq("user_id", user_id).eq("part_id", part_id).execute()
                st.toast("🗑️ ลบจากรายการโปรดแล้ว")
            else:
                supabase.table("favorites").insert({"user_id": user_id, "part_id": part_id}).execute()
                st.toast("⭐ บันทึกเป็นรายการโปรดแล้ว")
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, part_id INTEGER, UNIQUE(user_id, part_id))")
            cursor.execute("SELECT id FROM favorites WHERE user_id = ? AND part_id = ?", (user_id, part_id))
            if cursor.fetchone():
                cursor.execute("DELETE FROM favorites WHERE user_id = ? AND part_id = ?", (user_id, part_id))
                st.toast("🗑️ ลบจากรายการโปรดแล้ว")
            else:
                cursor.execute("INSERT INTO favorites (user_id, part_id) VALUES (?, ?)", (user_id, part_id))
                st.toast("⭐ บันทึกเป็นรายการโปรดแล้ว")
            conn.commit(); conn.close()
        return True
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาดในระบบฐานข้อมูล: {e}")
        return False

def get_user_favorites(user_id):
    try:
        if USE_SUPABASE:
            res = supabase.table("favorites").select("part_id").eq("user_id", user_id).execute()
            return [r["part_id"] for r in res.data]
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, part_id INTEGER, UNIQUE(user_id, part_id))")
            cursor.execute("SELECT part_id FROM favorites WHERE user_id = ?", (user_id,))
            rows = cursor.fetchall(); conn.close()
            return [r["part_id"] for r in rows]
    except:
        return []

# ---------------------------
# UI CUSTOMIZATION (SIDEBAR)
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
    
    st.divider()
    st.header("🎯 ตัวกรองการค้นหา")
    max_dist = st.slider("📏 ระยะทางสูงสุด (กม.)", 0, 100, 50)
    min_match = st.slider("🤖 ความแม่นยำ AI (%)", 0, 100, 40)
    st.session_state.max_dist = max_dist
    st.session_state.min_match = min_match / 100

    st.divider()
    with st.expander("🛠️ Developer Tools (Debug DB)"):
        st.write("ตรวจสอบข้อมูลในฐานข้อมูล")
        db_tables = ["users", "favorites", "shops", "shop_parts", "part_embeddings"]
        selected_table = st.selectbox("เลือกตารางเพื่อดูข้อมูล", db_tables)
        if st.button("👁️ ดึงข้อมูลตาราง", use_container_width=True):
            try:
                if USE_SUPABASE:
                    res = supabase.table(selected_table).select("*").limit(100).execute()
                    st.dataframe(res.data)
                else:
                    conn = get_db_connection()
                    st.dataframe(conn.execute(f"SELECT * FROM {selected_table} LIMIT 100").fetchall())
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
.stApp { background-color: #F8FAFC; }
/* Force dark text for ALL main content elements (Tabs, Alerts, Labels) */
[data-testid="stMain"] h1, [data-testid="stMain"] h2, [data-testid="stMain"] h3, 
[data-testid="stMain"] p, [data-testid="stMain"] span, [data-testid="stMain"] label, 
[data-testid="stMain"] div, [data-testid="stMain"] .stMarkdown, 
[data-testid="stMain"] button[data-baseweb="tab"] p { 
    color: #1E293B !important; 
}
/* Re-fix Button text (Yellow on Blue) since we used global div selector above */
[data-testid="stMain"] div.stButton > button, 
[data-testid="stMain"] div.stLinkButton > a { 
    color: #FBBF24 !important; 
}
/* Full-screen Dialog for Mobile (Google Lens style) */
@media (max-width: 640px) {
    div[data-testid="stDialog"] div[role="dialog"] {
        width: 100vw !important;
        height: 100vh !important;
        min-width: 100vw !important;
        min-height: 100vh !important;
        margin: 0 !important;
        padding: 0 !important;
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        border-radius: 0 !important;
    }
    div[data-testid="stDialog"] [data-testid="stVerticalBlock"] {
        padding: 0 !important;
    }
}
.stProgress > div > div > div > div { background-color: #1E3A8A !important; }
</style>
"""
st.markdown(theme_css, unsafe_allow_html=True)

# --------------------------
# SCREENS
# --------------------------
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

# (Session state moved to top)

def render_main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    @st.cache_resource
    def load_clip_model():
        model, preprocess = clip.load("ViT-B/32", device=device)
        return model, preprocess
    model, preprocess = load_clip_model()

    @st.cache_resource
    def load_vectors_cached():
        if USE_SUPABASE:
            # Join via query or multiple calls (Supabase doesn't do complex joins as easily as SQL)
            # Best way: create a VIEW in Supabase or just fetch what we need.
            # For now, let's fetch from part_embeddings and join shops/parts via ID
            res = supabase.table("part_embeddings").select("*, shop_parts(*, shops(*))").execute()
            data = res.data
            if not data: return None, []
            vectors, items = [], []
            for d in data:
                # Flatten the Supabase nested structure
                try:
                    sp = d["shop_parts"]
                    s = sp["shops"]
                    item_dict = {
                        "id": sp["id"], "part_name": sp["part_name"], "image": sp["image"],
                        "shop_name": s["shop_name"], "latitude": s["latitude"], 
                        "longitude": s["longitude"], "google_map_link": s["google_map_link"]
                    }
                    vec = np.array(d["embedding"]).astype("float32")
                    vec = vec / np.linalg.norm(vec)
                    vectors.append(vec); items.append(item_dict)
                except: continue
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT sp.id, sp.part_name, sp.image, s.shop_name, s.latitude, s.longitude, s.google_map_link, pe.embedding FROM part_embeddings pe JOIN shop_parts sp ON pe.part_id=sp.id JOIN shops s ON sp.shop_id=s.id")
            rows = cursor.fetchall(); conn.close()
            if not rows: return None, []
            vectors, items = [], []
            for d in rows:
                item_dict = dict(d)
                vec = np.array(json.loads(item_dict["embedding"])).astype("float32")
                vec = vec / np.linalg.norm(vec)
                vectors.append(vec); items.append(item_dict)
        
        if not vectors: return None, []
        vectors = np.array(vectors)
        idx = faiss.IndexFlatIP(vectors.shape[1]); idx.add(vectors)
        return idx, items

    with st.spinner("📦 กำลังโหลดข้อมูล..."):
        idx, items = load_vectors_cached()

    if idx is None:
        st.warning("⚠️ ฐานข้อมูลว่างเปล่า กรุณาเพิ่มข้อมูลอะไหล่ใน Supabase/SQLite ก่อนใช้งานครับ")
        if st.button("🔄 โหลดข้อมูลใหม่ (Refresh Cache)", use_container_width=True):
            st.cache_resource.clear()
            st.rerun()
    
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
        if idx is None: return []
        D, I = idx.search(q_vec, min(200, len(items)))
        results, seen = [], set()

        # Expand Keywords for Smart Filtering
        search_terms = []
        if q_text:
            q_low = q_text.lower()
            search_terms.append(q_low)
            for category, syns in SYNONYM_MAP.items():
                if q_low == category or any(s in q_low for s in syns):
                    search_terms.extend(syns)
            search_terms = list(set(search_terms))

        for score, i in zip(D[0], I[0]):
            if i == -1: continue
            item = items[i]
            if item["id"] in seen: continue
            
            # Smart Filter
            if search_terms:
                name_low = item["part_name"].lower()
                if not any(term in name_low for term in search_terms): 
                    continue

            seen.add(item["id"])
            R = 6371
            dlat, dlon = math.radians(item["latitude"]-lat), math.radians(item["longitude"]-lng)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(item["latitude"])) * math.sin(dlon/2)**2
            dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            results.append({
                "id": item["id"], "part_name": item["part_name"], "image": item["image"], "shop_name": item["shop_name"],
                "distance": dist, "score": float(max(0, min(1, score))), "map": item["google_map_link"]
            })
        return results

    st.title("🔧 FindSpares AI Search")
    
    # NEW: My Favorites Tab
    tab_search, tab_fav = st.tabs(["🔍 ค้นหาอะไหล่", "⭐ รายการโปรด"])
    
    @st.dialog("📸 FindSpares Scanner", width="large")
    def camera_modal():
        c_img = st.camera_input("แสกนอะไหล่", label_visibility="collapsed")
        if c_img:
            with st.spinner("🔎 Searching..."):
                img = Image.open(c_img).convert("RGB")
                vec = encode_image(img)
                res = search_parts(vec, 13.2839, 100.9289)
                st.session_state.results = sorted(res, key=lambda x: (-x["score"], x["distance"]))
                st.session_state.page = 1
                st.rerun()

    with tab_search:
        st.info("📍 ค้นหาด้วยชื่อ หรือ อัปโหลด/ถ่ายรูป")
        # Unified Google-style Search Bar
        scol, ccol = st.columns([7, 1])
        with scol:
            q = st.text_input("🔍 พิมพ์ชื่ออะไหล่ หรือ อัปโหลดรูป", key="search_q", label_visibility="collapsed")
        with ccol:
            if st.button("📸", key="btn_cam_modal", help="เปิดกล้องแสกนอะไหล่"):
                camera_modal()

        # File uploader (hidden but functional)
        up = st.file_uploader("📁 อัปโหลดรูปภาพ", type=["jpg","png","jpeg"], label_visibility="collapsed")
        
        # Logic: Auto-trigger search for text or upload
        if q or up:
            with st.spinner("🔎 กำลังประมวลผล..."):
                if up:
                    img = Image.open(up).convert("RGB")
                    vec = encode_image(img)
                    res = search_parts(vec, 13.2839, 100.9289)
                elif q:
                    res = search_parts(encode_text(q), 13.2839, 100.9289, q)
                
                if 'res' in locals():
                    st.session_state.results = sorted(res, key=lambda x: (-x["score"], x["distance"]))
                    st.session_state.page = 1

        if st.session_state.get("results"):
            # Apply Sidebar Filters
            max_d = st.session_state.get("max_dist", 50)
            min_m = st.session_state.get("min_match", 0.4)
            
            filtered_res = [r for r in st.session_state.results if r["distance"] <= max_d and r["score"] >= min_m]
            
            if filtered_res:
                render_grid(filtered_res)
            else:
                st.warning(f"🔎 ไม่พบอะไหล่ภายในระยะ {max_d} กม. หรือ Match > {int(min_m*100)}% ลองปรับตัวกรองที่แถบด้านข้างดูครับ")

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