"""
Cultural profiles per language: greetings, respectful forms, tone, number/date formatting.
Extensible: add future languages as dict entries without code changes.
"""

CULTURAL_PROFILES = {
    "en": {
        "code": "en",
        "name": "English (Nigeria)",
        "greetings": {
            "morning": "Good morning",
            "afternoon": "Good afternoon",
            "evening": "Good evening",
            "generic": "Hello",
            "formal": "Dear Sir/Madam",
        },
        "respectful_forms": ["Sir", "Madam", "Dear customer"],
        "tone": "polite, concise, professional",
        "honorifics": ["Mr.", "Mrs.", "Dr."],
        "number_format": {"thousands_sep": ",", "decimal_sep": ".", "currency_symbol": "₦", "currency_code": "NGN"},
        "date_format": "%d/%m/%Y",
        "time_format": "%I:%M %p",
        "plural_rules": "english",
        "week_start": "Monday",
    },
    "ha": {
        "code": "ha",
        "name": "Hausa",
        "greetings": {
            "morning": "Barka da safiya",
            "afternoon": "Barka da rana",
            "evening": "Barka da yamma",
            "generic": "Sannu",
            "formal": "Mai girma",
            "response": "Lafiya lau",
        },
        "respectful_forms": ["Malam", "Hajiya", "Alhaji", "Ya", "Abokin ciniki mai daraja"],
        "tone": "respectful, warm, elder-honoring, uses 'Don Allah' for please",
        "honorifics": ["Malam", "Hajiya", "Alhaji", "Sarki"],
        "number_format": {"thousands_sep": ",", "decimal_sep": ".", "currency_symbol": "₦", "currency_code": "NGN"},
        "date_format": "%d/%m/%Y",
        "time_format": "%I:%M %p",
        "plural_rules": "hausa",
        "week_start": "Monday",
        "notes": "Avoid direct demand; use respectful indirect request. Use Barka greetings by time of day.",
    },
    "yo": {
        "code": "yo",
        "name": "Yorùbá",
        "greetings": {
            "morning": "Ẹ ku owurọ",
            "afternoon": "Ẹ ku ọsan",
            "evening": "Ẹ ku irọlẹ",
            "generic": "Bawo",
            "formal": "Ẹ ku owurọ, Olowo ori mi",
            "elder": "Ẹ ku owurọ sir/ma",
        },
        "respectful_forms": ["Ẹ", "Baba", "Mama", "Oga", "Onibara ọwọn"],
        "tone": "highly respectful, proverb-friendly, emphasizes community and elder respect, uses Ẹ for you (plural/respect)",
        "honorifics": ["Baba", "Mama", "Oga", "Chief", "Olori"],
        "number_format": {"thousands_sep": ",", "decimal_sep": ".", "currency_symbol": "₦", "currency_code": "NGN"},
        "date_format": "%d/%m/%Y",
        "time_format": "%I:%M %p",
        "plural_rules": "yoruba",
        "week_start": "Monday",
        "notes": "Use Ẹ (respectful you). Time-based greetings critical: Ẹ ku owurọ/ọsan/irọlẹ.",
    },
    "ig": {
        "code": "ig",
        "name": "Igbo",
        "greetings": {
            "morning": "Ụtụtụ ọma",
            "afternoon": "Ehihie ọma",
            "evening": "Mgbede ọma",
            "generic": "Ndewo",
            "formal": "Dee / Daa (Sir/Madam)",
        },
        "respectful_forms": ["Dee", "Daa", "Nna", "Nne", "Ezigbo onye ahịa"],
        "tone": "warm, communal, respectful, emphasizes kinship (Nna/Nne)",
        "honorifics": ["Dee", "Daa", "Chief", "Ichie", "Mazi"],
        "number_format": {"thousands_sep": ",", "decimal_sep": ".", "currency_symbol": "₦", "currency_code": "NGN"},
        "date_format": "%d/%m/%Y",
        "time_format": "%I:%M %p",
        "plural_rules": "igbo",
        "week_start": "Monday",
        "notes": "Use Ndewo generic. Family terms Nna/Nne for respect.",
    },
    "pcm": {
        "code": "pcm",
        "name": "Nigerian Pidgin",
        "greetings": {
            "morning": "How for morning",
            "afternoon": "How for afternoon",
            "evening": "How for evening",
            "generic": "How far",
            "formal": "My oga",
        },
        "respectful_forms": ["Oga", "Madam", "My brother", "My sister", "My correct customer"],
        "tone": "friendly, informal, empathetic, direct but warm, uses Abeg, Oya, No vex",
        "honorifics": ["Oga", "Madam", "Chief"],
        "number_format": {"thousands_sep": ",", "decimal_sep": ".", "currency_symbol": "₦", "currency_code": "NGN"},
        "date_format": "%d/%m/%Y",
        "time_format": "%I:%M %p",
        "plural_rules": "pidgin",
        "week_start": "Monday",
        "notes": "Most accessible across Nigeria. Keep short, mix English. Ideal fallback for low literacy.",
    },
    # Future languages — registry will add rows inactive; profiles can be added lazily
    "ff": {
        "code": "ff",
        "name": "Fulfulde",
        "greetings": {"generic": "Jam tan", "morning": "Jam waali", "formal": "Jam e jam"},
        "respectful_forms": ["Moodibbo"],
        "tone": "respectful, pastoral-heritage aware",
        "honorifics": ["Moodibbo"],
        "number_format": {"thousands_sep": ",", "decimal_sep": ".", "currency_symbol": "₦", "currency_code": "NGN"},
        "date_format": "%d/%m/%Y",
        "time_format": "%I:%M %p",
        "plural_rules": "fulfulde",
        "week_start": "Monday",
    },
    "kr": {
        "code": "kr",
        "name": "Kanuri",
        "greetings": {"generic": "Lafiya?"},
        "respectful_forms": ["Alhaji"],
        "tone": "respectful",
        "honorifics": ["Alhaji"],
        "number_format": {"thousands_sep": ",", "decimal_sep": ".", "currency_symbol": "₦", "currency_code": "NGN"},
        "date_format": "%d/%m/%Y",
        "time_format": "%I:%M %p",
        "plural_rules": "kanuri",
        "week_start": "Monday",
    },
    "tiv": {
        "code": "tiv",
        "name": "Tiv",
        "greetings": {"generic": "M sugh"},
        "respectful_forms": ["Orya"],
        "tone": "respectful",
        "honorifics": ["Orya"],
        "number_format": {"thousands_sep": ",", "decimal_sep": ".", "currency_symbol": "₦", "currency_code": "NGN"},
        "date_format": "%d/%m/%Y",
        "time_format": "%I:%M %p",
        "plural_rules": "tiv",
        "week_start": "Monday",
    },
}


def get_profile(code: str) -> dict:
    """Return cultural profile with English fallback."""
    return CULTURAL_PROFILES.get(code, CULTURAL_PROFILES["en"])


def format_number(value, lang_code: str = "en") -> str:
    """Format number per language profile."""
    profile = get_profile(lang_code)
    fmt = profile.get("number_format", {})
    thousands = fmt.get("thousands_sep", ",")
    decimal = fmt.get("decimal_sep", ".")
    # Simple formatting; respects Nigerian NGN same across languages
    try:
        num = float(value)
        # Format with comma thousands then replace if needed
        s = f"{num:,.2f}"
        if thousands != "," or decimal != ".":
            s = s.replace(",", "THOU").replace(".", decimal).replace("THOU", thousands)
        return s
    except Exception:
        return str(value)


def format_date(date_obj, lang_code: str = "en") -> str:
    """Format date per language profile."""
    profile = get_profile(lang_code)
    fmt = profile.get("date_format", "%d/%m/%Y")
    try:
        return date_obj.strftime(fmt)
    except Exception:
        return str(date_obj)


def get_greeting(lang_code: str, time_of_day: str = "generic") -> str:
    """Get greeting for language and time of day."""
    profile = get_profile(lang_code)
    return profile.get("greetings", {}).get(time_of_day) or profile.get("greetings", {}).get("generic", "Hello")
