from typing import Any, Dict, List, Optional, Protocol, Tuple, Type


class PlatformClient(Protocol):
    """
    Protocol defining the interface for IDP Platform operations.
    This allows for flexible dependency injection and testing.
    """

    async def generate(self, json: Dict[str, Any]) -> str:
        """
        Generate user stories using Azure AI services.

        Args:
            context_entity: Dictionary representing the product modification (ContextEntity)

        Returns:
            str: Generated user stories
        """
        ...

    async def get_entity_by_id(self, id: str) -> Dict[str, Any]:
        """
        Retrieve an entity by its unique identifier.

        Args:
            id (str): The unique identifier of the entity to retrieve.

        Returns:
            Dict[str, Any]: A dictionary containing the entity's data.

        Raises:
            Exception: If the entity cannot be found or retrieval fails.
        """
        ...

    async def get_entities(self, query_params: Dict[str, str]) -> List[Dict[str, Any]]:
        """
        Asynchronously retrieves a list of entities based on the provided story request parameters.

        Args:
            query_params  (Dict[str, str]): A dictionary containing parameters for the story request.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an entity.
        """
        ...

    async def get_similar_entities(self, payload: Dict[str, Any]) -> Any:
        """
        Asynchronously retrieves similar entities from the external platform API.

        Args:
            payload (Dict[str, Any]): The data to find similar entities.

        Returns:
            Any: The response from the external platform API.
        """
        ...

    # --- added for theme generation: the chat-completions structured-output call on the concrete
    # PlatformRestClient (not in the original Protocol). ---
    async def agenerate(
        self,
        message: List[Dict[str, str]],
        model_params: Optional[Dict[str, Any]] = None,
        output_function: Optional[Type] = None,
        trace_id: Optional[str] = None,
        bearer_token: Optional[str] = None,
    ) -> Tuple[Any, Optional[str], int]:
        """
        Chat-completions call. With ``output_function`` (a pydantic model) set, the response is
        constrained to that schema and parsed. Returns ``(data, error, status_code)``.
        """
        ...
