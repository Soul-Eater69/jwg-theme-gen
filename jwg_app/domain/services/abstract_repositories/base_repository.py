"""Generic base abstract repository for all data access operations.

This module defines the generic interface for repository operations
following the repository pattern and dependency inversion principle.
"""

from abc import ABC, abstractmethod
from typing import Any, Generic, List, Optional, TypeVar

T = TypeVar("T")


class IBaseRepository(ABC, Generic[T]):
    """Generic abstract base class for repository operations.

    This interface defines common database operations for all entities,
    enabling dependency inversion and easier testing through mocking.

    Type Parameters:
        T: The model type this repository handles
    """

    @abstractmethod
    async def create(self, **kwargs) -> T:
        """Create a new record.

        Args:
            **kwargs: Entity-specific fields required for creation

        Returns:
            Created model instance
        """
        pass

    @abstractmethod
    async def get_by_field(self, field_name: str, field_value: Any) -> List[T]:
        """Get records by any field.

        Args:
            field_name: Name of the field to search
            field_value: Value to match

        Returns:
            List of model instances matching the criteria
        """
        pass

    @abstractmethod
    async def get_by_filter(self, filter_expression: Any) -> List[T]:
        """Get records by a filter expression.

        Args:
            filter_expression: SQLAlchemy filter expression

        Returns:
            List of model instances matching the criteria
        """
        pass

    @abstractmethod
    async def get_all(self) -> List[T]:
        """Get all records.

        Returns:
            List of model instances
        """
        pass

    @abstractmethod
    async def update(self, filter_expression: Any, **fields) -> Optional[T]:
        """Update any fields of a record by matching a filter expression.

        Args:
            filter_expression: SQLAlchemy filter expression
            **fields: Field names and values to update

        Returns:
            Updated model instance if found, None otherwise
        """
        pass

    @abstractmethod
    async def delete(self, field_name: str, field_value: Any) -> bool:
        """Delete a record.

        Args:
            field_name: Name of the field to match
            field_value: Value to match

        Returns:
            True if deletion was successful
        """
        pass
