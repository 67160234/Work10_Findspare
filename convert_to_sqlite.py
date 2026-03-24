import pymysql
import sqlite3
import json

# ---------------------------
# SETTINGS (YOUR UNIVERSITY MYSQL)
# ---------------------------
DB_CONFIG = {
    "host": "angsila.cs.buu.ac.th",
    "user": "s67160234",
    "password": "kVeBVERH",
    "database": "s67160234",
    "port": 3306
}

def migrate():
    print("[INFO] Connecting to MySQL at angsila.cs.buu.ac.th...")
    try:
        mysql_conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    except Exception as e:
        print(f"[ERROR] Error connecting to MySQL: {e}")
        return

    print("[INFO] Creating SQLite database file: database.db...")
    sqlite_conn = sqlite3.connect("database.db")
    sqlite_curr = sqlite_conn.cursor()

    # Tables to migrate
    tables = ["shops", "shop_parts", "part_embeddings", "part_synonyms"]

    for table in tables:
        print(f"[PROCESS] Migrating table: {table}...")
        
        # Get data from MySQL
        with mysql_conn.cursor() as mysql_curr:
            mysql_curr.execute(f"SELECT * FROM {table}")
            rows = mysql_curr.fetchall()

        if not rows:
            print(f"⚠️ Table {table} is empty. Skipping.")
            continue

        # Get column names
        cols = rows[0].keys()
        cols_str = ", ".join(cols)
        placeholders = ", ".join(["?"] * len(cols))

        # Create table in SQLite
        sqlite_curr.execute(f"DROP TABLE IF EXISTS {table}")
        sqlite_curr.execute(f"CREATE TABLE {table} ({cols_str})")

        # Insert data into SQLite
        data_to_insert = [tuple(row.values()) for row in rows]
        sqlite_curr.executemany(f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})", data_to_insert)

    sqlite_conn.commit()
    mysql_conn.close()
    sqlite_conn.close()
    print("✅ Migration complete! Your 'database.db' is ready.")
    print("👉 Now upload 'database.db' and the updated 'app.py' to GitHub.")

if __name__ == "__main__":
    migrate()
