class InventoryError(Exception):
    """Base domain exception for inventory operations."""


class ValidationError(InventoryError):
    """Raised when input data is invalid."""


class StockUnderflowError(InventoryError):
    """Raised when an outbound transaction would make stock negative."""
