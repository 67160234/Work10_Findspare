import sqlite3
import json

def migrate():
    try:
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        
        sql_lines = [
            "-- FindSpares Seed Data for Supabase",
            "TRUNCATE shops, shop_parts, part_embeddings, users, favorites CASCADE;",
            ""
        ]
        
        # 1. Shops (id, shop_name, address, phone, latitude, longitude, google_map_link)
        cursor.execute("SELECT id, shop_name, latitude, longitude, google_map_link FROM shops")
        shops = cursor.fetchall()
        for s in shops:
            sid, name, lat, lng, link = s
            name_esc = name.replace("'", "''")
            link_esc = link.replace("'", "''") if link else ""
            sql_lines.append(f"INSERT INTO shops (id, shop_name, latitude, longitude, google_map_link) VALUES ({sid}, '{name_esc}', {lat}, {lng}, '{link_esc}');")
        
        sql_lines.append("")
        
        # 2. Shop Parts (id, shop_id, part_name, category, image, ai_part)
        cursor.execute("SELECT id, shop_id, part_name, image FROM shop_parts")
        parts = cursor.fetchall()
        for p in parts:
            pid, sid, name, img = p
            name_esc = name.replace("'", "''")
            img_esc = img.replace("'", "''") if img else ""
            sql_lines.append(f"INSERT INTO shop_parts (id, shop_id, part_name, image) VALUES ({pid}, {sid}, '{name_esc}', '{img_esc}');")
            
        sql_lines.append("")
        
        # 3. Embeddings (part_id, embedding)
        cursor.execute("SELECT part_id, embedding FROM part_embeddings")
        embs = cursor.fetchall()
        for i, e in enumerate(embs):
            pid, vec_str = e
            # Use json.dumps for JSONB compatibility in Supabase
            sql_lines.append(f"INSERT INTO part_embeddings (id, part_id, embedding) VALUES ({i+1}, {pid}, '{vec_str}');")
            
        with open("seed_data.sql", "w", encoding="utf-8") as f:
            f.write("\n".join(sql_lines))
            
        print("Done: seed_data.sql generated.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
