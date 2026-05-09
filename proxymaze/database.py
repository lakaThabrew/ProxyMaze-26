"""Database connection and session management"""
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import ProgrammingError
from .models import Base
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./proxymaze.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables (skip if they already exist)"""
    try:
        # Check if tables already exist
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        
        # Get tables from our models
        model_tables = set(Base.metadata.tables.keys())
        
        # Only create tables that don't exist
        if existing_tables:
            logger.info(f"Found existing tables: {existing_tables}")
            # Create only missing tables
            Base.metadata.create_all(bind=engine)
            logger.info("Database schema verified/updated")
        else:
            # First run: create all tables
            Base.metadata.create_all(bind=engine)
            logger.info("Database initialized with all tables")
    except ProgrammingError as e:
        if "already exists" in str(e):
            logger.info("Tables already exist, skipping creation")
        else:
            logger.error(f"Database initialization error: {str(e)}")
            raise
    except Exception as e:
        logger.error(f"Unexpected error during database initialization: {str(e)}")
        raise


def get_db() -> Session:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
