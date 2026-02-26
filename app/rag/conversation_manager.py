"""
ConversationManager class for managing in-memory conversation history
"""
import logging

logger = logging.getLogger(__name__)

class ConversationManager:
    """
    Manages the conversation history for a chat session.
    
    This class is responsible for:
    - Maintaining the conversation history in memory
    - Adding user and assistant messages to the history
    - Providing access to the complete history
    - Clearing the history when needed
    """
    
    def __init__(self, system_message="You are a helpful AI assistant."):
        """
        Initialize the conversation manager with a system message.
        
        Args:
            system_message: The initial system message that defines the assistant's behavior
        """
        self.chat_history = [{"role": "system", "content": system_message}]
        logger.debug("ConversationManager initialized with system message")
        
    def add_user_message(self, message):
        """
        Add a user message to the conversation history.
        
        Args:
            message: The user's message content
        """
        self.chat_history.append({"role": "user", "content": message})
        logger.debug(f"Added user message to history (length: {len(message)})")
        logger.info(f"Conversation history now has {len(self.chat_history)} messages")
        
    def add_assistant_message(self, message):
        """
        Add an assistant message to the conversation history.
        
        Args:
            message: The assistant's message content
        """
        self.chat_history.append({"role": "assistant", "content": message})
        logger.debug(f"Added assistant message to history (length: {len(message)})")
        logger.info(f"Conversation history now has {len(self.chat_history)} messages")
        
    def get_history(self):
        """
        Get the complete conversation history.
        
        Returns:
            List of message dictionaries with 'role' and 'content' keys
        """
        return self.chat_history
    
    def clear_history(self, preserve_system_message=True):
        """
        Clear the conversation history.
        
        Args:
            preserve_system_message: Whether to preserve the initial system message
        """
        if preserve_system_message and self.chat_history and self.chat_history[0]["role"] == "system":
            system_message = self.chat_history[0]
            self.chat_history = [system_message]
            logger.debug("Cleared conversation history, preserved system message")
        else:
            self.chat_history = []
            logger.debug("Cleared entire conversation history including system message")
