"""Програмні правила: перевірка змісту вилучених даних.

Схема (`app/schema.py`) каже, що IBAN — рядок, а сума — число. Чи це
справжній IBAN і чи сходиться сума з позиціями, схема не знає. Це знає
документ: у рахунку багато надлишковості — контрольні розряди в кодах,
підсумки, що мають дорівнювати сумі рядків, ПДВ, що має дорівнювати
п'ятій частині. Модель, яка прочитала 8 замість 3, цю надлишковість
порушує, і код це бачить. Правила тут не знають ні про модель, ні про
веб-рівень: на вході — перевірений за схемою словник, на виході — перелік
знайдених проблем.

Набір правил задано (розділ 2 практичної роботи):

* IBAN: формат і контрольне число за ISO 13616 (залишок mod 97);
* код постачальника й покупця: 8 цифр ЄДРПОУ з контрольним розрядом
  або 10 цифр РНОКПП;
* арифметика: кількість × ціна = сума в кожному рядку; сума рядків =
  разом без ПДВ; ПДВ = 20 % (або нуль для неплатника); разом + ПДВ =
  до сплати — з допуском на округлення, який ви оберете й обґрунтуєте;
* дати: існують, не з майбутнього, строк дії не раніше дати рахунку;
* покупець — ваша компанія (`reference/company.json`);
* постачальник відомий, і IBAN збігається з довідником
  (`reference/suppliers.json`);
* обовʼязкові поля присутні.

Рішення — ваші: які правила дають помилку, а які — попередження; чи
перевіряти правило, якщо потрібного поля немає; як рахувати гроші, щоб
0,1 + 0,2 не дало 0,30000000000000004.
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

REFERENCE_DIR = Path(__file__).resolve().parent.parent / "reference"


@dataclass
class Issue:
    """Проблема, знайдена правилом.

    `field` — шлях до поля, наприклад `supplier.iban` чи `items.1.amount`
    (другий рядок: індекс — з нуля); сторінка підсвічує поле з таким
    шляхом. `rule` — коротка назва
    правила. `message` — пояснення для людини, яка перевірятиме документ.
    `severity` — `error` або `warning`; що з цього випливає для рішення,
    вирішує `app/extraction.py`.
    """

    field: str
    rule: str
    message: str
    severity: str = "error"


def load_reference() -> tuple[dict, list[dict]]:
    """Прочитати реквізити своєї компанії й довідник постачальників."""
    company = json.loads((REFERENCE_DIR / "company.json").read_text(encoding="utf-8"))
    suppliers = json.loads((REFERENCE_DIR / "suppliers.json").read_text(encoding="utf-8"))
    return company, suppliers


def clean_text(value: str) -> str:
    value = value.replace("ʼ", "'")
    value = value.replace("’", "'")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _valid_iban(value: str) -> bool:
    iban = _compact(value).upper()
    if not re.fullmatch(r"UA[0-9]{27}", iban):
        return False

    rearranged = iban[4:] + iban[:4]
    remainder = 0
    for character in rearranged:
        expanded = (
            str(ord(character) - ord("A") + 10)
            if character.isalpha()
            else character
        )
        for digit in expanded:
            remainder = (remainder * 10 + int(digit)) % 97
    return remainder == 1


def _valid_edrpou(value: str) -> bool:
    code = _compact(value)
    if not re.fullmatch(r"[0-9]{8}", code):
        return False

    weights = [1, 2, 3, 4, 5, 6, 7]
    if code[0] in "345":
        weights = [7, 1, 2, 3, 4, 5, 6]

    total = sum(weight * int(digit) for weight, digit in zip(weights, code[:7]))
    check_digit = total % 11
    if check_digit == 10:
        total = sum(
            (weight + 2) * int(digit)
            for weight, digit in zip(weights, code[:7])
        )
        check_digit = total % 11 % 10
    return int(code[-1]) == check_digit


def _decimal(value: object) -> Decimal:
    normalized = re.sub(r"\s+", "", str(value)).replace(",", ".")
    number = Decimal(normalized)
    if not number.is_finite():
        raise InvalidOperation
    return number


def check(document: dict) -> list[Issue]:
    """Застосувати правила до вилученого документа.

    Порожній перелік означає, що правила нічого не знайшли, — а не що
    документ прочитано правильно. Різниця між цими двома речами і є
    предметом перевірки на наборі зразків.
    """
    issues = []

    company, suppliers = load_reference()

    if document.get("document_type") != "invoice":
        issues.append(
            Issue(
                "document_type",
                "document_type",
                "Документ не є рахунком."
            )
        )
        return issues

    required_fields = [
        "invoice_number",
        "date",
        "supplier",
        "buyer",
        "items",
        "total_without_vat",
        "vat",
        "total_due",
    ]

    for field in required_fields:
        if not document.get(field):
            issues.append(
                Issue(
                    field,
                    "required",
                    "Обов'язкове поле відсутнє."
                )
            )

    invoice_date = document.get("date")

    if invoice_date:
        try:
            invoice_date = date.fromisoformat(invoice_date)

            if invoice_date > date.today():
                issues.append(
                    Issue(
                        "date",
                        "date",
                        "Дата рахунку знаходиться в майбутньому."
                    )
                )

        except ValueError:
            issues.append(
                Issue(
                    "date",
                    "date",
                    "Неправильний формат дати."
                )
            )

    valid_until = document.get("valid_until")

    if valid_until and document.get("date"):
        try:
            valid_date = date.fromisoformat(valid_until)
            invoice_date = date.fromisoformat(document["date"])

            if valid_date < invoice_date:
                issues.append(
                    Issue(
                        "valid_until",
                        "date",
                        "Строк дії не може бути раніше дати рахунку."
                    )
                )

        except ValueError:
            issues.append(
                Issue(
                    "valid_until",
                    "date",
                    "Неправильний формат строку дії."
                )
            )

    buyer = document.get("buyer")

    if buyer:
        buyer_code = buyer.get("code")
        if buyer_code:
            if re.fullmatch(r"[0-9]{8}", _compact(buyer_code)):
                if not _valid_edrpou(buyer_code):
                    issues.append(
                        Issue(
                            "buyer.code",
                            "edrpou_checksum",
                            "Неправильний контрольний розряд ЄДРПОУ покупця."
                        )
                    )
            elif not re.fullmatch(r"[0-9]{10}", _compact(buyer_code)):
                issues.append(
                    Issue(
                        "buyer.code",
                        "code_format",
                        "Код має бути 8 цифр ЄДРПОУ або 10 цифр РНОКПП."
                    )
                )

        if clean_text(buyer.get("name", "")) != clean_text(company["name"]):
            issues.append(
                Issue(
                    "buyer.name",
                    "buyer",
                    "Неправильний покупець."
                )
            )

        if buyer.get("code") != company["code"]:
            issues.append(
                Issue(
                    "buyer.code",
                    "buyer",
                    "Неправильний код покупця."
                )
            )

    supplier = document.get("supplier")

    if supplier:
        supplier_name = supplier.get("name")
        supplier_code = supplier.get("code")
        supplier_iban = supplier.get("iban")

        if supplier_code:
            if re.fullmatch(r"[0-9]{8}", _compact(supplier_code)):
                if not _valid_edrpou(supplier_code):
                    issues.append(
                        Issue(
                            "supplier.code",
                            "edrpou_checksum",
                            "Неправильний контрольний розряд ЄДРПОУ постачальника."
                        )
                    )
            elif not re.fullmatch(r"[0-9]{10}", _compact(supplier_code)):
                issues.append(
                    Issue(
                        "supplier.code",
                        "code_format",
                        "Код має бути 8 цифр ЄДРПОУ або 10 цифр РНОКПП."
                    )
                )

        if supplier_iban:
            compact_iban = _compact(supplier_iban)
            if not re.fullmatch(r"UA[0-9]{27}", compact_iban, re.IGNORECASE):
                issues.append(
                    Issue(
                        "supplier.iban",
                        "iban_format",
                        "IBAN має містити UA та 27 цифр."
                    )
                )
            elif not _valid_iban(supplier_iban):
                issues.append(
                    Issue(
                        "supplier.iban",
                        "iban_checksum",
                        "Контрольна сума IBAN неправильна."
                    )
                )

        found_supplier = None

        for item in suppliers:
            if (
                item["name"] == supplier_name
                or item["code"] == supplier_code
            ):
                found_supplier = item
                break

        if found_supplier is None:
            issues.append(
                Issue(
                    "supplier",
                    "supplier",
                    "Постачальника немає у довіднику."
                )
            )
        elif supplier_iban:
            iban1 = _compact(supplier_iban).upper()
            iban2 = _compact(found_supplier["iban"]).upper()
            if iban1 != iban2:
                issues.append(
                    Issue(
                        "supplier.iban",
                        "iban",
                        "IBAN не відповідає довіднику."
                    )
                )

    items = document.get("items", [])

    total_items = Decimal("0")
    items_valid = True

    for number, item in enumerate(items):

        try:
            quantity = _decimal(item.get("quantity"))
            price = _decimal(item.get("price"))
            amount = _decimal(item.get("amount"))

            calculated = quantity * price

            calculated = calculated.quantize(Decimal("0.01"))
            amount = amount.quantize(Decimal("0.01"))

            if calculated != amount:
                issues.append(
                    Issue(
                        f"items.{number}.amount",
                        "arithmetic",
                        "Кількість × ціна не дорівнює сумі."
                    )
                )

            total_items += amount

        except (InvalidOperation, TypeError):
            items_valid = False
            issues.append(
                Issue(
                    f"items.{number}",
                    "number",
                    "Неправильні числові значення."
                )
            )

    total_without_vat = None
    if document.get("total_without_vat") not in (None, ""):
        try:
            total_without_vat = _decimal(document["total_without_vat"])
        except (InvalidOperation, TypeError):
            issues.append(
                Issue(
                    "total_without_vat",
                    "number",
                    "Неправильне числове значення суми без ПДВ."
                )
            )

    if (
        items_valid
        and total_without_vat is not None
        and total_items.quantize(Decimal("0.01"))
        != total_without_vat.quantize(Decimal("0.01"))
    ):
        issues.append(
            Issue(
                "total_without_vat",
                "arithmetic",
                "Сума позицій не дорівнює сумі без ПДВ."
            )
        )

    vat = None
    if document.get("vat") not in (None, ""):
        try:
            vat = _decimal(document["vat"])
        except (InvalidOperation, TypeError):
            issues.append(
                Issue(
                    "vat",
                    "number",
                    "Неправильне числове значення ПДВ."
                )
            )

    supplier_info = None

    if supplier:
        for item in suppliers:
            if (
                item["name"] == supplier.get("name")
                or item["code"] == supplier.get("code")
            ):
                supplier_info = item
                break

    if supplier_info and total_without_vat is not None and vat is not None:
        if supplier_info["vat_payer"]:
            expected_vat = total_without_vat * Decimal("0.20")
        else:
            expected_vat = Decimal("0")

        if vat.quantize(Decimal("0.01")) != expected_vat.quantize(
            Decimal("0.01")
        ):
            issues.append(
                Issue(
                    "vat",
                    "vat",
                    "Неправильно розрахований ПДВ."
                )
            )

    total_due = None
    if document.get("total_due") not in (None, ""):
        try:
            total_due = _decimal(document["total_due"])
        except (InvalidOperation, TypeError):
            issues.append(
                Issue(
                    "total_due",
                    "number",
                    "Неправильне числове значення суми до сплати."
                )
            )

    if (
        total_due is not None
        and total_without_vat is not None
        and vat is not None
    ):
        expected_total = total_without_vat + vat
        if total_due.quantize(Decimal("0.01")) != expected_total.quantize(
            Decimal("0.01")
        ):
            issues.append(
                Issue(
                    "total_due",
                    "arithmetic",
                    "Сума без ПДВ + ПДВ не дорівнює сумі до сплати."
                )
            )

    return issues
    
