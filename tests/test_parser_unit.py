from src.parser import (
    extract_dates,
    infer_announcement_date_from_text,
    parse_polish_date,
)


def test_extract_dates_polish_words():
    text = (
        "Z dniem 11 lipca 2024 r. do Programu Wspierania Płynności przystąpiła "
        "spółka. Zmiana systemu notowań zostanie wprowadzona od sesji w dniu "
        "16 lipca 2024 r."
    )
    join, effective = extract_dates(text)
    assert join == "2024-07-11"
    assert effective == "2024-07-16"


def test_extract_dates_numeric_format():
    text = (
        "Z dniem 01.08.2025 do Programu Wspierania Płynności przystąpiła spółka. "
        "Zmiana systemu notowań nastąpi od sesji w dniu 06.08.2025."
    )
    join, effective = extract_dates(text)
    assert join == "2025-08-01"
    assert effective == "2025-08-06"


def test_parse_polish_date_variants():
    assert parse_polish_date("11 lipca 2024 r.") == "2024-07-11"
    assert parse_polish_date("16.07.2024") == "2024-07-16"


def test_infer_announcement_date_from_text():
    text = (
        "Komunikat opublikowany 7 października 2024 r. Z dniem 11 lipca 2024 r. "
        "spółka przystąpiła do Programu Wspierania Płynności."
    )
    inferred = infer_announcement_date_from_text(text)
    assert inferred == "2024-10-07"
