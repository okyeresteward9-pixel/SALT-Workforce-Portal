import os
import psycopg2
from psycopg2.extras import RealDictCursor

UPLOAD_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "static",
    "uploads"
)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "pdf",
    "docx",
    "xlsx",
    "txt"
}


def allowed_file(filename):
    return (
        "." in filename and
        filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


def get_db():

    database_url = os.environ.get("DATABASE_URL")

    if database_url:

        conn = psycopg2.connect(
            database_url,
            cursor_factory=RealDictCursor,
            options="-c timezone=UTC"
        )

    else:

        conn = psycopg2.connect(
            host="localhost",
            database="salt_portal",
            user="salt_user",
            password="ChooseAStrongpassword",
            cursor_factory=RealDictCursor,
            options="-c timezone=UTC"
        )

    return conn