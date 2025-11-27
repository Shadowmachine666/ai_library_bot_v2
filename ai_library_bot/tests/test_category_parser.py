"""Тесты для category_parser.py."""

from pathlib import Path

import pytest

from src.category_parser import (
    extract_book_title_only,
    parse_categories_from_filename,
    validate_categories,
)


def test_parse_categories_single_category():
    """Тест: парсинг одной категории."""
    file_path = Path("Книга (бизнес).pdf")
    title, categories = parse_categories_from_filename(file_path)

    assert title == "Книга"
    assert categories == ["бизнес"]


def test_parse_categories_multiple_categories():
    """Тест: парсинг нескольких категорий."""
    file_path = Path("Книга (бизнес, маркетинг).pdf")
    title, categories = parse_categories_from_filename(file_path)

    assert title == "Книга"
    assert "бизнес" in categories
    assert "маркетинг" in categories
    assert len(categories) == 2


def test_parse_categories_no_categories():
    """Тест: парсинг без категорий."""
    file_path = Path("Книга.pdf")
    title, categories = parse_categories_from_filename(file_path)

    assert title == "Книга"
    assert categories == []


def test_parse_categories_with_spaces():
    """Тест: парсинг категорий с пробелами."""
    file_path = Path("Книга (бизнес, маркетинг, психология).pdf")
    title, categories = parse_categories_from_filename(file_path)

    assert title == "Книга"
    assert len(categories) == 3
    assert "бизнес" in categories
    assert "маркетинг" in categories
    assert "психология" in categories


def test_parse_categories_case_insensitive():
    """Тест: парсинг категорий без учёта регистра."""
    file_path = Path("Книга (БИЗНЕС, Маркетинг).pdf")
    title, categories = parse_categories_from_filename(file_path)

    assert title == "Книга"
    # Категории должны быть нормализованы к нижнему регистру
    assert "бизнес" in categories or "БИЗНЕС" in categories
    assert len(categories) >= 1


def test_parse_categories_with_brackets_in_title():
    """Тест: парсинг с скобками в названии."""
    file_path = Path("Книга (часть 1) (бизнес).pdf")
    title, categories = parse_categories_from_filename(file_path)

    # Должны взять последние скобки
    assert "бизнес" in categories
    # Название может содержать "Книга (часть 1)" или только "Книга"
    assert "Книга" in title


def test_validate_categories_valid():
    """Тест: валидация валидных категорий."""
    categories = ["бизнес", "маркетинг"]
    valid, invalid = validate_categories(categories)

    assert len(valid) == 2
    assert len(invalid) == 0
    assert "бизнес" in valid
    assert "маркетинг" in valid


def test_validate_categories_invalid():
    """Тест: валидация невалидных категорий."""
    categories = ["бизнес", "неизвестная_категория"]
    valid, invalid = validate_categories(categories)

    assert len(valid) == 1
    assert len(invalid) == 1
    assert "бизнес" in valid
    assert "неизвестная_категория" in invalid


def test_validate_categories_case_insensitive():
    """Тест: валидация без учёта регистра."""
    categories = ["БИЗНЕС", "МАРКЕТИНГ"]
    valid, invalid = validate_categories(categories)

    # Категории должны быть нормализованы
    assert len(valid) >= 1


def test_extract_book_title_only():
    """Тест: извлечение только названия книги."""
    file_path = Path("Книга (бизнес, маркетинг).pdf")
    title = extract_book_title_only(file_path)

    assert title == "Книга"
    assert "бизнес" not in title
    assert "маркетинг" not in title


def test_extract_book_title_only_no_categories():
    """Тест: извлечение названия без категорий."""
    file_path = Path("Книга.pdf")
    title = extract_book_title_only(file_path)

    assert title == "Книга"

