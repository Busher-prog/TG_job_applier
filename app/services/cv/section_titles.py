"""Standard CV section headings per document language (document content, not UI)."""

from __future__ import annotations

TITLES: dict[str, dict[str, str]] = {
    "en": {
        "professional_summary": "Professional Summary", "experience": "Professional Experience",
        "additional_experience": "Additional Experience", "achievements": "Key Achievements",
        "skills": "Skills", "software": "Software & Tools", "transferable_skills": "Transferable Skills",
        "education": "Education", "languages": "Languages", "projects": "Projects",
        "certifications": "Certifications & Courses", "portfolio": "Portfolio", "contact": "Contact",
        "soft_skills": "Personal Skills", "present": "Present", "in_progress": "in progress",
        "relevant_experience": "Relevant Experience",
    },
    "de": {
        "professional_summary": "Profil", "experience": "Berufserfahrung",
        "additional_experience": "Weitere Erfahrung", "achievements": "Erfolge",
        "skills": "Kenntnisse", "software": "Software & Tools", "transferable_skills": "Übertragbare Kompetenzen",
        "education": "Ausbildung", "languages": "Sprachen", "projects": "Projekte",
        "certifications": "Zertifikate & Weiterbildung", "portfolio": "Portfolio", "contact": "Kontakt",
        "soft_skills": "Persönliche Stärken", "present": "heute", "in_progress": "laufend",
        "relevant_experience": "Relevante Erfahrung",
    },
    "ru": {
        "professional_summary": "Профессиональное резюме", "experience": "Опыт работы",
        "additional_experience": "Дополнительный опыт", "achievements": "Ключевые достижения",
        "skills": "Навыки", "software": "Программы и инструменты", "transferable_skills": "Переносимые навыки",
        "education": "Образование", "languages": "Языки", "projects": "Проекты",
        "certifications": "Сертификаты и курсы", "portfolio": "Портфолио", "contact": "Контакты",
        "soft_skills": "Личные качества", "present": "наст. время", "in_progress": "обучение продолжается",
        "relevant_experience": "Релевантный опыт",
    },
    "uk": {
        "professional_summary": "Професійне резюме", "experience": "Досвід роботи",
        "additional_experience": "Додатковий досвід", "achievements": "Ключові досягнення",
        "skills": "Навички", "software": "Програми та інструменти", "transferable_skills": "Перенос­ні навички",
        "education": "Освіта", "languages": "Мови", "projects": "Проєкти",
        "certifications": "Сертифікати та курси", "portfolio": "Портфоліо", "contact": "Контакти",
        "soft_skills": "Особисті якості", "present": "дотепер", "in_progress": "навчання триває",
        "relevant_experience": "Релевантний досвід",
    },
}
TITLES["uk"]["transferable_skills"] = "Переносні навички"

LEVEL_LABELS: dict[str, dict[str, str]] = {
    "de": {"Native": "Muttersprache", "Fluent": "Fließend", "Unknown": ""},
    "ru": {"Native": "Родной", "Fluent": "Свободно", "Unknown": ""},
    "uk": {"Native": "Рідна", "Fluent": "Вільно", "Unknown": ""},
    "en": {"Native": "Native", "Fluent": "Fluent", "Unknown": ""},
}


def titles_for(lang: str) -> dict[str, str]:
    return TITLES.get(lang.split("-")[0].lower(), TITLES["en"])


def level_label(lang: str, level: str) -> str:
    labels = LEVEL_LABELS.get(lang.split("-")[0].lower(), LEVEL_LABELS["en"])
    return labels.get(level, level)
