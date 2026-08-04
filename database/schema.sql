DROP TABLE IF EXISTS task_comments CASCADE;
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS announcements CASCADE;
DROP TABLE IF EXISTS notifications CASCADE;
DROP TABLE IF EXISTS tasks CASCADE;
DROP TABLE IF EXISTS attendance CASCADE;
DROP TABLE IF EXISTS employees CASCADE;

CREATE TABLE employees (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    email VARCHAR(255) UNIQUE,
    password TEXT,
    role VARCHAR(50),
    phone VARCHAR(50),
    department VARCHAR(255),
    profile_pic TEXT,
    theme VARCHAR(20) DEFAULT 'light'
);

CREATE TABLE attendance (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER REFERENCES employees(id) ON DELETE CASCADE,
    clock_in TIMESTAMP,
    clock_out TIMESTAMP,
    latitude VARCHAR(50),
    longitude VARCHAR(50)
);

CREATE TABLE tasks (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255),
    description TEXT,
    assigned_to INTEGER REFERENCES employees(id),
    deadline DATE,
    status VARCHAR(50) DEFAULT 'Pending',
    created_by INTEGER REFERENCES employees(id),
    created_at TIMESTAMP,
    completed_at TIMESTAMP,
    carried_forward BOOLEAN DEFAULT FALSE,
    original_deadline DATE,
    note TEXT,
    reply TEXT,
    admin_reply TEXT,
    task_scope VARCHAR(50) DEFAULT 'personal'
);

CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES employees(id),
    message TEXT,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP
);

CREATE TABLE announcements (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255),
    message TEXT,
    created_by INTEGER REFERENCES employees(id),
    created_at TIMESTAMP,
    file_path TEXT
);

CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    sender_id INTEGER REFERENCES employees(id),
    receiver_id INTEGER REFERENCES employees(id),
    message TEXT,
    created_at TIMESTAMP,
    is_read BOOLEAN DEFAULT FALSE,
    seen BOOLEAN DEFAULT FALSE,
    file_name TEXT,
    file_path TEXT,
    deleted BOOLEAN DEFAULT FALSE,
    edited BOOLEAN DEFAULT FALSE
);

CREATE TABLE task_comments (
    id SERIAL PRIMARY KEY,
    task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    sender_id INTEGER REFERENCES employees(id),
    sender_role VARCHAR(50),
    message TEXT,
    parent_comment_id INTEGER REFERENCES task_comments(id) ON DELETE CASCADE,
    visibility VARCHAR(50) DEFAULT 'public',
    comment_type VARCHAR(50) DEFAULT 'reply',
    created_at TIMESTAMP
);