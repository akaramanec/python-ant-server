def calculate_calories(hr, age, weight, sex, duration_seconds=1):
    """
    Розрахунок спалених калорій за формулою Keytel et al.
    Враховує стать (sex: 'male' або 'female').
    Повертає ккал за вказану тривалість (за замовчуванням 1 секунда).
    hr — той самий пульс, що показується користувачу (у т.ч. після correction_factor трекера).
    """

    def _is_female(s):
        if s is None:
            return False
        t = str(s).strip().lower()
        return t in ('female', 'f', 'woman', 'жінка', 'дівчина')

    # 1. Визначаємо ккал за хвилину залежно від статі
    if _is_female(sex):
        # Дефолтна для жінок
        kcal_per_minute = (-20.4022 + (0.4472 * hr) - (0.1263 * weight) + (0.0740 * age)) / 4.184
    else:
        # Для чоловіків або якщо стать не розпізнано
        kcal_per_minute = (-55.0969 + (0.6309 * hr) + (0.1988 * weight) + (0.2017 * age)) / 4.184

    # 2. Переводимо в ккал за секунду (винесено за межі if/else, щоб працювало для всіх)
    kcal_per_seconds = kcal_per_minute / 60

    # Вираховуємо загальну кількість за тренування
    return max(0, kcal_per_seconds * duration_seconds)