"""Консольний бот-помічник з адресною книгою та днями народження."""

from collections import UserDict
from datetime import datetime, date, timedelta
from functools import wraps
import os
import pickle


# ---------------------------------------------------------------------------
# Моделі даних
# ---------------------------------------------------------------------------
class Field:
    """Базове поле запису."""

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return str(self.value)


class Name(Field):
    """Ім'я контакту (обов'язкове, не порожнє)."""

    def __init__(self, value):
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be empty.")
        super().__init__(value)


class Phone(Field):
    """Телефон: рівно 10 цифр."""

    def __init__(self, value):
        value = value.strip()
        if not (value.isdigit() and len(value) == 10):
            raise ValueError("Phone number must contain exactly 10 digits.")
        super().__init__(value)


class Birthday(Field):
    """День народження у форматі DD.MM.YYYY."""

    DATE_FORMAT = "%d.%m.%Y"

    def __init__(self, value):
        try:
            parsed = datetime.strptime(value.strip(), self.DATE_FORMAT).date()
        except ValueError as error:
            raise ValueError("Invalid date format. Use DD.MM.YYYY") from error
        if parsed > date.today():
            raise ValueError("Birthday cannot be in the future.")
        super().__init__(parsed)

    def __str__(self):
        return self.value.strftime(self.DATE_FORMAT)


class Record:
    """Запис контакту: ім'я, телефони та (опційно) день народження."""

    def __init__(self, name):
        self.name = Name(name)
        self.phones = []
        self.birthday = None

    def add_phone(self, phone):
        """Додає телефон; дублікати не дозволені."""
        phone_obj = Phone(phone)
        if any(p.value == phone_obj.value for p in self.phones):
            raise ValueError(f"Phone {phone_obj} already exists for {self.name}.")
        self.phones.append(phone_obj)

    def remove_phone(self, phone):
        """Видаляє телефон контакту."""
        phone_obj = self.find_phone(phone)
        if phone_obj is None:
            raise ValueError(f"Phone {phone} not found for {self.name}.")
        self.phones.remove(phone_obj)

    def edit_phone(self, old_phone, new_phone):
        """Змінює старий номер на новий з усіма перевірками."""
        new_obj = Phone(new_phone)  # спочатку валідуємо новий номер
        old_obj = self.find_phone(old_phone)

        if old_obj is None:
            raise ValueError(f"Phone {old_phone} not found for {self.name}.")

        if old_obj.value == new_obj.value:
            raise ValueError("New phone is the same as the old one.")

        if self.find_phone(new_obj.value) is not None:
            raise ValueError(f"Phone {new_phone} already exists for {self.name}.")

        old_obj.value = new_obj.value

    def find_phone(self, phone):
        """Повертає об'єкт Phone або None."""
        for phone_obj in self.phones:
            if phone_obj.value == phone:
                return phone_obj
        return None

    def add_birthday(self, birthday):
        """Додає день народження (лише один на контакт)."""
        if self.birthday is not None:
            raise ValueError(f"{self.name} already has a birthday: {self.birthday}.")
        self.birthday = Birthday(birthday)

    def __str__(self):
        phones = "; ".join(p.value for p in self.phones) or "no phones"
        birthday = str(self.birthday) if self.birthday else "not set"
        return f"Contact name: {self.name}, phones: {phones}, birthday: {birthday}"


class AddressBook(UserDict):
    """Адресна книга: словник записів за ім'ям."""

    def add_record(self, record):
        """Додає запис до книги."""
        self.data[record.name.value] = record

    def find(self, name):
        """Повертає запис за ім'ям або None."""
        return self.data.get(name)

    def delete(self, name):
        """Видаляє запис за ім'ям."""
        if name not in self.data:
            raise KeyError(name)
        del self.data[name]

    @staticmethod
    def _next_birthday(born, today):
        """Дата найближчого дня народження (29.02 у невисокосний рік -> 01.03)."""
        for year in (today.year, today.year + 1):
            try:
                candidate = born.replace(year=year)
            except ValueError:
                candidate = date(year, 3, 1)
            if candidate >= today:
                return candidate
        return None  # недосяжно, але задовольняє лінтер

    def get_upcoming_birthdays(self, days=7):
        """Повертає список {'name', 'congratulation_date'} на наступні `days` днів.

        Якщо день народження випадає на вихідні, привітання переноситься
        на понеділок.
        """
        today = date.today()
        upcoming = []
        for record in self.data.values():
            if record.birthday is None:
                continue
            birthday = self._next_birthday(record.birthday.value, today)
            if not 0 <= (birthday - today).days <= days:
                continue
            congrat = birthday
            if congrat.weekday() == 5:    # субота -> понеділок
                congrat += timedelta(days=2)
            elif congrat.weekday() == 6:  # неділя -> понеділок
                congrat += timedelta(days=1)
            upcoming.append({"name": record.name.value, "congratulation_date": congrat})
        upcoming.sort(key=lambda item: item["congratulation_date"])
        for item in upcoming:
            item["congratulation_date"] = item["congratulation_date"].strftime(
                Birthday.DATE_FORMAT
            )
        return upcoming


# ---------------------------------------------------------------------------
# Збереження та завантаження адресної книги
# ---------------------------------------------------------------------------
def save_data(book, filename="addressbook.pkl"):
    """Зберігає адресну книгу у файл за допомогою pickle."""
    with open(filename, "wb") as file:
        pickle.dump(book, file)


def load_data(filename="addressbook.pkl"):
    """Завантажує адресну книгу з файлу або створює нову.

    Якщо файл пошкоджений, він не перезаписується: його копія
    зберігається як <filename>.bak, а програма стартує з порожньою книгою.
    """
    try:
        with open(filename, "rb") as file:
            return pickle.load(file)
    except FileNotFoundError:
        return AddressBook()
    except (
        pickle.UnpicklingError,
        EOFError,
        AttributeError,
        ImportError,
        IndexError,
        ValueError,
    ) as error:
        backup = filename + ".bak"
        os.replace(filename, backup)
        print(f"Cannot load saved data ({error}). Old file kept as {backup}.")
        return AddressBook()


# ---------------------------------------------------------------------------
# Декоратор обробки помилок
# ---------------------------------------------------------------------------
def input_error(func):
    """Перехоплює помилки вводу та повертає зрозуміле повідомлення."""

    @wraps(func)
    def inner(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValueError as error:
            return str(error) or "Invalid input."
        except KeyError as error:
            return f"Contact {error.args[0]} not found."
        except IndexError:
            return "Not enough arguments. Please check the command."

    return inner


def require_args(args, count, usage):
    """Перевіряє достатню кількість аргументів команди."""
    if len(args) < count:
        raise ValueError(f"Not enough arguments. Usage: {usage}")


# ---------------------------------------------------------------------------
# Обробники команд
# ---------------------------------------------------------------------------
@input_error
def add_contact(args, book: AddressBook):
    """add [name] [phone]: новий контакт або додатковий телефон."""
    require_args(args, 2, "add [name] [phone]")
    name, phone, *_ = args

    # Спочатку валідуємо телефон, щоб не створювати невалідні записи в книзі
    Phone(phone)

    record = book.find(name)
    message = "Contact updated."

    if record is None:
        record = Record(name)
        book.add_record(record)
        message = "Contact added."

    record.add_phone(phone)
    return message


@input_error
def change_contact(args, book: AddressBook):
    """change [name] [old phone] [new phone]: змінити телефон."""
    require_args(args, 3, "change [name] [old phone] [new phone]")
    name, old_phone, new_phone, *_ = args
    record = book.find(name)
    if record is None:
        raise KeyError(name)
    record.edit_phone(old_phone, new_phone)
    return "Phone updated."


@input_error
def show_phone(args, book: AddressBook):
    """phone [name]: показати телефони контакту."""
    require_args(args, 1, "phone [name]")
    record = book.find(args[0])
    if record is None:
        raise KeyError(args[0])
    if not record.phones:
        return f"{record.name} has no phones."
    return f"{record.name}: " + ", ".join(p.value for p in record.phones)


@input_error
def show_all(_args, book: AddressBook):
    """all: показати всі контакти."""
    if not book.data:
        return "Address book is empty."
    return "\n".join(str(record) for record in book.data.values())


@input_error
def add_birthday(args, book: AddressBook):
    """add-birthday [name] [DD.MM.YYYY]: додати день народження."""
    require_args(args, 2, "add-birthday [name] [DD.MM.YYYY]")
    name, birthday, *_ = args
    record = book.find(name)
    if record is None:
        raise KeyError(name)
    record.add_birthday(birthday)
    return "Birthday added."


@input_error
def show_birthday(args, book: AddressBook):
    """show-birthday [name]: показати день народження."""
    require_args(args, 1, "show-birthday [name]")
    record = book.find(args[0])
    if record is None:
        raise KeyError(args[0])
    if record.birthday is None:
        return f"{record.name} has no birthday set."
    return f"{record.name}'s birthday: {record.birthday}"


@input_error
def birthdays(_args, book: AddressBook):
    """birthdays: привітання на наступний тиждень."""
    upcoming = book.get_upcoming_birthdays()
    if not upcoming:
        return "No birthdays in the next 7 days."
    return "\n".join(
        f"{item['congratulation_date']}: {item['name']}" for item in upcoming
    )


# ---------------------------------------------------------------------------
# Головний цикл
# ---------------------------------------------------------------------------
def parse_input(user_input):
    """Розбирає рядок на команду та аргументи."""
    parts = user_input.strip().split()
    if not parts:
        return "", []
    cmd, *args = parts
    return cmd.lower(), args


def main():
    """Запуск бота із завантаженням та збереженням адресної книги."""
    book = load_data()
    print("Welcome to the assistant bot!")

    try:
        while True:
            user_input = input("Enter a command: ")
            command, args = parse_input(user_input)

            if command in ["close", "exit"]:
                print("Good bye!")
                break
            if command == "":
                continue
            if command == "hello":
                print("How can I help you?")
            elif command == "add":
                print(add_contact(args, book))
            elif command == "change":
                print(change_contact(args, book))
            elif command == "phone":
                print(show_phone(args, book))
            elif command == "all":
                print(show_all(args, book))
            elif command == "add-birthday":
                print(add_birthday(args, book))
            elif command == "show-birthday":
                print(show_birthday(args, book))
            elif command == "birthdays":
                print(birthdays(args, book))
            else:
                print("Invalid command.")
    except (KeyboardInterrupt, EOFError):
        print("\nGood bye!")
    finally:
        save_data(book)


if __name__ == "__main__":
    main()
