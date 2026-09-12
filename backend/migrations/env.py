"""Use the same database URL and SQLite instance path as the Flask application."""
from alembic import context
from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402

app = create_app(initialize_database=False)
with app.app_context():
    with db.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=db.metadata,
                          render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()
