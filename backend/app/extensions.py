"""Shared Flask extension singletons.

Kept in their own module so models and the app factory can import `db` without
creating a circular dependency on the application package.
"""
from __future__ import annotations

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Project-wide SQLAlchemy 2.0 declarative base."""


db = SQLAlchemy(model_class=Base)
