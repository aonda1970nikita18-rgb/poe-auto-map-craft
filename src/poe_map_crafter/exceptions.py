class PoECrafterError(Exception):
    """Базовая ошибка приложения."""


class InitializationError(PoECrafterError):
    """Не удалось подготовить окружение перед крафтом."""


class SafetyStopError(PoECrafterError):
    """Аварийная или плановая остановка по безопасности."""


class RecognitionError(PoECrafterError):
    """Не удалось однозначно распознать элемент интерфейса."""


class CurrencyError(PoECrafterError):
    """Проблема с валютой в инвентаре."""


class CraftingError(PoECrafterError):
    """Ошибка в процессе крафта карты."""