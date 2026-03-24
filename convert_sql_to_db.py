import sqlite3
import re
import os

sql_file = r"c:\Users\Lenovo\Downloads\ModelAi\GitHub_Upload_Ready\findspares.sql"
db_file = r"c:\Users\Lenovo\Downloads\ModelAi\GitHub_Upload_Ready\database.db"

# Exact schemas from SQL study
SCHEMAS = {
    "shops": "id INTEGER PRIMARY KEY, shop_name TEXT, address TEXT, phone TEXT, latitude REAL, longitude REAL, google_map_link TEXT",
    "shop_parts": "id INTEGER PRIMARY KEY, shop_id INTEGER, part_name TEXT, category TEXT, image TEXT, ai_part TEXT",
    "part_embeddings": "part_id INTEGER, embedding TEXT",
    "part_synonyms": "id INTEGER PRIMARY KEY, part_name TEXT, synonym TEXT"
}

def migrate():
    if os.path.exists(db_file):
        os.remove(db_file)
    
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Create tables
    for table, schema in SCHEMAS.items():
        cursor.execute(f"CREATE TABLE {table} ({schema})")

    with open(sql_file, "r", encoding="utf8") as f:
        content = f.read()

    # Regex for INSERT INTO `table` (...) VALUES (...);
    for table in SCHEMAS.keys():
        pattern = rf"INSERT INTO `{table}` .*? VALUES\s*(.*?);"
        matches = re.finditer(pattern, content, re.DOTALL | re.IGNORECASE)
        
        for match in matches:
            # We must handle those MySQL backticks and potential syntax differences
            # but since we defined the tables exactly, we can just rewrite the query
            # or try to execute it as is after simple cleanup
            query = match.group(0).replace("`", "") # Remove backticks
            
            # SQLite doesn't support nested VALUES in some old versions if too many
            # but usually it's fine for modern sqlite3.
            
            try:
                cursor.execute(query)
            except Exception as e:
                print(f"[ERROR] Failed to insert into {table}: {e}")

    conn.commit()
    conn.close()
    print(f"[INFO] Successfully created {db_file}")

if __name__ == "__main__":
    migrate()
