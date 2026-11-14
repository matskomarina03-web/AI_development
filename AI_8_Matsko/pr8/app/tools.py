"""Інструменти помічника: що модель може попросити виконати і як це
перевіряється.

Єдине місце застосунку, яке знає і про модель, і про сервіс магазину
(`shop/service.py`). Тут описано інструменти для моделі, тут перевіряють
аргументи, які вона повернула, і тут викликають сервіс. Модуль моделі
(`app/llm.py`) не знає, які інструменти існують, а сервіс не знає, що
його викликає модель.

Набір можливостей помічника задано (розділ 2 практичної роботи):

* перелік замовлень клієнта і стан конкретного замовлення;
* пошук товарів у каталозі й картка товару;
* наявність товару на складі;
* вартість і строк доставки;
* заявка на повернення товару.

Скасування замовлення — на ваш розсуд, з обґрунтуванням. Адміністративні
операції сервісу моделі недоступні за жодних умов.

Функції нижче — заготовки. Рішення з розділу 2 практичної роботи:

* скільки інструментів і які саме: одна функція сервісу — один
  інструмент, чи інакше; як їх назвати й описати, щоб модель обирала
  правильно — і коли не обирала жодного;
* які параметри має кожен інструмент і як їх обмежити схемою: типи,
  переліки допустимих значень, формати, межі;
* звідки береться, хто клієнт: з аргументів, які заповнила модель, чи з
  контексту сеансу, який модель не бачить і не може змінити;
* що перевірити після схеми: чи існує замовлення, чиє воно, чи
  дозволена операція;
* що повертати моделі з результату сервісу: запис цілком чи лише
  потрібні поля — і чому;
* як повідомляти моделі про відмову й помилку так, щоб вона могла
  пояснити їх клієнтові, не вигадуючи.
"""

import json

from dataclasses import dataclass

from jsonschema import Draft202012Validator

from shop import service


@dataclass
class Context:
    """Те, що відомо про сеанс незалежно від моделі.

    `customer_id` — клієнт, який увійшов. У справжньому застосунку його
    бере веб-рівень із сесії після автентифікації; тут його обирають на
    сторінці. Модель цього поля не бачить і змінити не може.
    """

    customer_id: str


@dataclass
class ToolResult:
    """Підсумок одного виклику інструмента.

    `status` — що сталося, наприклад: `ok` — виконано; `rejected` —
    виклик не пройшов ваших перевірок, сервіс не викликався; `error` —
    сервіс відмовив або не відповів. `content` — те, що піде моделі як
    результат виклику. `reason` — пояснення для журналу й сторінки, якщо
    виклик відхилено або він завершився помилкою. `arguments` —
    аргументи після перевірки, якщо до неї дійшло. Склад полів — ваше
    рішення; `app/assistant.py` і сторінка працюють з тим, що тут буде.
    """

    status: str
    content: dict | list | str | None = None
    reason: str | None = None
    arguments: dict | None = None


def specs() -> list[dict]:
    """Повернути описи інструментів у форматі, який приймає API моделі.

    Кожен опис — назва, пояснення для моделі, коли інструмент потрібен, і
    JSON Schema параметрів. Модель бачить лише це: ані коду функцій, ані
    сервісу.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "list_orders",
                "description": (
                    "Повертає список замовлень поточного клієнта. "
                    "Використовуй для питання про замовлення клієнта."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_order",
                "description": (
                    "Повертає основну інформацію про конкретне замовлення. "
                    "Використовуй, коли клієнт питає про стан свого замовлення."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Номер замовлення.",
                        }
                    },
                    "required": ["order_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_products",
                "description": (
                    "Шукає товари в каталозі за назвою або описом."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Що потрібно знайти.",
                        },
                        "category": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Категорія товару, якщо відома.",
                        },
                        "max_price": {
                            "type": "number",
                            "minimum": 0,
                            "description": "Максимальна ціна, якщо її вказав клієнт.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 50,
                            "description": "Максимальна кількість результатів.",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_product",
                "description": (
                    "Повертає інформацію про конкретний товар за його SKU."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sku": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Артикул товару.",
                        }
                    },
                    "required": ["sku"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_stock",
                "description": (
                    "Повертає кількість товару на складі та інформацію "
                    "про очікувану поставку."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sku": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Артикул товару.",
                        }
                    },
                    "required": ["sku"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delivery_quote",
                "description": (
                    "Розраховує вартість і строк доставки товарів "
                    "у вказане місто."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Місто доставки в Україні.",
                        },
                        "method": {
                            "type": "string",
                            "enum": ["branch", "courier", "pickup"],
                            "description": "Спосіб доставки.",
                        },
                        "items": {
                            "type": "array",
                            "description": "Товари для доставки.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "sku": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                    "quantity": {
                                        "type": "integer",
                                        "minimum": 1
                                    },
                                },
                                "required": ["sku", "quantity"],
                                "additionalProperties": False,
                            },
                            "minItems": 1,
                        },
                    },
                    "required": ["city", "method", "items"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_return",
                "description": (
                    "Створює заявку на повернення товару з отриманого "
                    "замовлення клієнта."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Номер замовлення.",
                        },
                        "sku": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Артикул товару.",
                        },
                        "reason": {
                            "type": "string",
                            "enum": [
                                "not_suitable",
                                "defect",
                                "wrong_item",
                                "damaged",
                            ],
                            "description": "Причина повернення.",
                        },
                        "quantity": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Кількість товарів.",
                        },
                        "comment": {
                            "type": "string",
                            "description": "Додатковий коментар клієнта.",
                        },
                    },
                    "required": [
                        "order_id",
                        "sku",
                        "reason",
                        "quantity",
                    ],
                    "additionalProperties": False,
                },
            },
        },
    ]

def make_result(status, content=None, reason=None, arguments=None):
    if status != "ok" and content is None:
        content = reason or "Виклик інструмента не виконано."

    return ToolResult(
        status=status,
        content=content,
        reason=reason,
        arguments=arguments,
    )

def validate_arguments(name, arguments):
    schema = next(
        (
            tool["function"]["parameters"]
            for tool in specs()
            if tool["function"]["name"] == name
        ),
        None,
    )
    if schema is None:
        return "Для цього інструмента немає схеми аргументів."

    errors = sorted(
        Draft202012Validator(schema).iter_errors(arguments),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if not errors:
        return None

    error = errors[0]
    path = ".".join(str(part) for part in error.absolute_path)
    parameter = f"Параметр {path}" if path else "Аргументи"

    if error.validator == "required":
        missing = sorted(set(error.validator_value) - set(error.instance))
        return f"Не вказано обов'язковий параметр: {', '.join(missing)}."

    if error.validator == "type":
        expected = {
            "array": "масивом",
            "integer": "цілим числом",
            "number": "числом",
            "object": "об'єктом",
            "string": "рядком",
        }.get(error.validator_value, error.validator_value)
        return f"{parameter} має бути {expected}."

    if error.validator == "enum":
        choices = ", ".join(str(value) for value in error.validator_value)
        return f"{parameter} має бути одним із значень: {choices}."

    if error.validator == "additionalProperties":
        unexpected = sorted(set(error.instance) - set(error.schema["properties"]))
        return f"Невідомий параметр: {', '.join(unexpected)}."

    if error.validator in {"minimum", "maximum"}:
        relation = "не меншим" if error.validator == "minimum" else "не більшим"
        return f"{parameter} має бути {relation} за {error.validator_value}."

    if error.validator in {"minItems", "minLength"}:
        return f"{parameter} не може бути порожнім."

    return f"{parameter} не відповідає схемі інструмента."

def call(name: str, raw_arguments: str, ctx: Context) -> ToolResult:
    """Виконати виклик інструмента, який запропонувала модель.

    `name` і `raw_arguments` — як їх повернула модель: назва й рядок з
    аргументами у JSON. Ні тому, ні іншому не можна вірити наперед:
    назви може не бути серед ваших інструментів, рядок може не бути
    JSON, аргументи можуть не пройти схему або стосуватися чужого
    замовлення.

    Жоден виняток звідси не має вийти назовні: будь-який результат —
    `ToolResult`.
    """
    allowed_tools = [
        "list_orders",
        "get_order",
        "search_products",
        "get_product",
        "get_stock",
        "delivery_quote",
        "create_return",
    ]

    if name not in allowed_tools:
        return make_result(
            "rejected",
            reason="Такого інструмента немає.",
        )

    if not isinstance(raw_arguments, str):
        return make_result(
            "rejected",
            reason="Аргументи мають бути рядком JSON.",
        )

    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return make_result(
            "rejected",
            reason="Аргументи мають бути правильним JSON.",
        )

    if not isinstance(arguments, dict):
        return make_result(
            "rejected",
            reason="Аргументи повинні бути JSON-об'єктом.",
        )

    customer_id = ctx.customer_id
    validation_error = validate_arguments(name, arguments)

    if validation_error:
        return make_result(
            "rejected",
            reason=validation_error,
            arguments=arguments,
        )

    try:

        if name == "list_orders":

            orders = service.list_orders(customer_id)

            result = []

            for order in orders:
                result.append({
                    "order_id": order["order_id"],
                    "date": order["created_at"],
                    "status": order["status"],
                    "status_label": order["status_label"],
                    "total": order["total"],
                    "items_count": order["items_count"],
                })

            return make_result(
                "ok",
                result,
                arguments=arguments,
            )

        if name == "get_order":

            order_id = arguments.get("order_id")

            if not order_id:
                return make_result(
                    "rejected",
                    reason="Не вказано номер замовлення.",
                    arguments=arguments,
                )

            order = service.get_order(order_id)

            if order["customer_id"] != customer_id:
                return make_result(
                    "rejected",
                    reason="Це замовлення належить іншому клієнту.",
                    arguments=arguments,
                )

            result = {
              "order_id": order["order_id"],
              "date": order["created_at"],
              "status": order["status"],
              "status_label": order["status_label"],
              "total": order["total"],
              "items": order["items"],
              "delivery": order["delivery"],
          }

            return make_result(
                "ok",
                result,
                arguments=arguments,
            )

        if name == "search_products":

            query = arguments.get("query")

            if not query:
                return make_result(
                    "rejected",
                    reason="Не вказано, що потрібно знайти.",
                    arguments=arguments,
                )

            products = service.search_products(
                query=query,
                category=arguments.get("category"),
                max_price=arguments.get("max_price"),
                limit=arguments.get("limit", 5),
            )

            result = []

            for product in products:
                result.append({
                    "sku": product["sku"],
                    "name": product["name"],
                    "category": product["category"],
                    "price": product["price"],
                })

            return make_result(
                "ok",
                result,
                arguments=arguments,
            )

        if name == "get_product":

            sku = arguments.get("sku")

            if not sku:
                return make_result(
                    "rejected",
                    reason="Не вказано SKU товару.",
                    arguments=arguments,
                )

            product = service.get_product(sku)

            result = {
                "sku": product["sku"],
                "name": product["name"],
                "category": product["category"],
                "price": product["price"],
                "weight": product["weight_kg"],
                "warranty": product["warranty_months"],
                "returnable": product["returnable"],
                "description": product["description"],
            }

            return make_result(
                "ok",
                result,
                arguments=arguments,
            )

        if name == "get_stock":

            sku = arguments.get("sku")

            if not sku:
                return make_result(
                    "rejected",
                    reason="Не вказано SKU товару.",
                    arguments=arguments,
                )

            stock = service.get_stock(sku)

            result = {
                "sku": sku,
                "available": stock["available"],
                "incoming": stock.get("expected_restock"),
            }

            return make_result(
                "ok",
                result,
                arguments=arguments,
            )

        if name == "delivery_quote":

            city = arguments.get("city")
            method = arguments.get("method")
            items = arguments.get("items")

            if not city or not method or not items:
                return make_result(
                    "rejected",
                    reason="Для доставки потрібні місто, спосіб доставки та товари.",
                    arguments=arguments,
                )

            quote = service.delivery_quote(
                city=city,
                method=method,
                items=items,
            )

            return make_result(
                "ok",
                quote,
                arguments=arguments,
            )

        if name == "create_return":

            order_id = arguments.get("order_id")
            sku = arguments.get("sku")
            reason = arguments.get("reason")
            quantity = arguments.get("quantity", 1)
            comment = arguments.get("comment")

            if not order_id or not sku or not reason:
                return make_result(
                    "rejected",
                    reason="Для повернення потрібні замовлення, товар і причина.",
                    arguments=arguments,
                )

            order = service.get_order(order_id)

            if order["customer_id"] != customer_id:
                return make_result(
                    "rejected",
                    reason="Це замовлення належить іншому клієнту.",
                    arguments=arguments,
                )

            return_data = service.create_return(
                order_id=order_id,
                sku=sku,
                reason=reason,
                quantity=quantity,
                comment=comment,
            )

            return make_result(
                "ok",
                return_data,
                arguments=arguments,
            )

    except service.ShopError as error:
        reason = str(error)
        return make_result(
            "error",
            content=reason,
            reason=reason,
            arguments=arguments,
        )

    except Exception as error:
        reason = "Внутрішня помилка сервісу магазину."
        return make_result(
            "error",
            content=reason,
            reason=reason,
            arguments=arguments,
        )

    return make_result(
        "rejected",
        reason="Виклик не був виконаний.",
        arguments=arguments,
    )
