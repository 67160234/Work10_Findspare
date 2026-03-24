-- 1. Create Shops table
CREATE TABLE shops (
    id SERIAL PRIMARY KEY,
    shop_name TEXT NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    google_map_link TEXT
);

-- 2. Create Shop Parts table
CREATE TABLE shop_parts (
    id SERIAL PRIMARY KEY,
    shop_id INTEGER REFERENCES shops(id),
    part_name TEXT NOT NULL,
    image TEXT
);

-- 3. Create Part Embeddings table
CREATE TABLE part_embeddings (
    id SERIAL PRIMARY KEY,
    part_id INTEGER REFERENCES shop_parts(id),
    embedding JSONB -- Storing numerical array as JSONB for flexibilty
);

-- 4. Create Users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT,
    password TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. Create Favorites table
CREATE TABLE favorites (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    part_id INTEGER REFERENCES shop_parts(id),
    UNIQUE(user_id, part_id)
);
