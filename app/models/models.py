#app/models/models.py

#=====================================================================================================#
#Copyright (c) 2026 Agilent Technologies All rights reserved worldwide.
#Agilent Confidential, Use is permitted only in accordance with applicable End User License Agreement.
#=====================================================================================================#

# Data models for user management, session tracking, query logging, OpenAI usage, and feedback.
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from app.utils.encryption_util import AESEncryptor




# Descriptor for encrypted fields
class EncryptedField:
    def __init__(self, name):
        self.name = name
        self.private_name = f'_{name}'

    def __get__(self, obj, objtype=None):
        value = getattr(obj, self.private_name, None)
        if value and hasattr(obj, 'encryptor'):
            return obj.encryptor.decrypt(value)
        return value

    def __set__(self, obj, value):
        if value and hasattr(obj, 'encryptor'):
            encrypted = obj.encryptor.encrypt(value)
            setattr(obj, self.private_name, encrypted)
        else:
            setattr(obj, self.private_name, value)

# Represents a user in the system
@dataclass
class User:
    encryptor: AESEncryptor = AESEncryptor()  # AES encryptor instance
    ad_user_id: str = EncryptedField('ad_user_id')  # Active Directory user ID (PII, encrypted)
    user_id: Optional[int] = None  # Internal user ID
    ad_user_id_hash: Optional[str] = None  # Deterministic hash for lookup
    details: Optional['UserDetails'] = None  # User details object
    sessions: List['UserSessions'] = field(default_factory=list)  # List of user sessions
    audit_logs: List['AuditLog'] = field(default_factory=list)  # List of audit logs

# Stores additional details about a user
@dataclass
class UserDetails:
    encryptor: AESEncryptor = AESEncryptor()  # AES encryptor instance
    user_name: str = EncryptedField('user_name')  # User's name (PII, encrypted)
    user_email: str = EncryptedField('user_email')  # User's email (PII, encrypted)
    location: Optional[str] = EncryptedField('location')  # User's location (PII, encrypted)
    department: Optional[str] = EncryptedField('department')  # User's department (PII, encrypted)
    role: Optional[str] = EncryptedField('role')  # User's role (PII, encrypted)
    user: Optional[User] = None  # Reference to the User

# Represents a session for a user
@dataclass
class UserSessions:
    session_id: str  # Unique session identifier
    id: Optional[int] = None  # Internal session ID
    user_id: Optional[int] = None  # Associated user ID
    session_start_timestamp: Optional[datetime] = None  # Session start time
    session_end_timestamp: Optional[datetime] = None  # Session end time
    user: Optional[User] = None  # Reference to the User
    queries: List['Queries'] = field(default_factory=list)  # List of queries in this session

# Represents a query made during a session
@dataclass
class Queries:
    session_id: int  # Associated session ID
    query_id: Optional[int] = None  # Query ID
    session: Optional[UserSessions] = None  # Reference to the session
    timestamp: Optional[datetime] = field(default_factory=datetime.now)  # Timestamp of the query
    openai_usages: List['OpenAIUsage'] = field(default_factory=list)  # List of OpenAI usage records
    details: Optional['QueryDetails'] = None  # Query details

# Tracks usage of OpenAI API for a query
@dataclass
class OpenAIUsage:
    timestamp: Optional[datetime] = field(default_factory=datetime.now)  # Timestamp of usage
    id: Optional[int] = None  # Usage record ID
    model: Optional[str] = None  # Model used
    call_type: Optional[str] = None  # Type of API call
    prompt_tokens: Optional[int] = None  # Number of prompt tokens
    completion_tokens: Optional[int] = None  # Number of completion tokens
    total_tokens: Optional[int] = None  # Total tokens used
    scenario: Optional[str] = None  # Scenario description
    prompt_cost: Optional[Decimal] = None  # Cost for prompt tokens
    completion_cost: Optional[Decimal] = None  # Cost for completion tokens
    total_cost: Optional[Decimal] = None  # Total cost
    query_id: Optional[int] = None  # Associated query ID
    user_id: Optional[int] = None  # FK to user_details.user_id
    query: Optional[Queries] = None  # Reference to the query

# Stores details about a specific query
@dataclass
class QueryDetails:
    query_id: Optional[int] = None  # Associated query ID
    user_query: Optional[str] = None  # The user's query text
    response: Optional[str] = None  # The response text
    latency_ms: Optional[int] = None  # Total latency in ms
    is_follow_up: bool = False  # Whether this is a follow-up query
    mode: Optional[str] = None  # Mode of the query
    persona: Optional[str] = None  # Persona used
    query: Optional[Queries] = None  # Reference to the query
    llm_latency_ms: Optional[int] = None  # LLM latency in ms
    search_latency_ms: Optional[int] = None  # Search latency in ms
    reranker_latency_ms: Optional[int] = None  # Reranker latency in ms
    sources: Optional[json] = None  # Sources used (JSON)
    features_json: Optional[json] = None  # Features (JSON)
    self_critique_metrics: Optional['SelfCritiqueMetrics'] = None  # Self-critique metrics

# Stores self-critique metrics for a query
@dataclass
class SelfCritiqueMetrics:
    query_id: Optional[int] = None  # Associated query ID
    refined_response: Optional[str] = None  # Refined response text
    critique_json: Optional[json] = None  # Critique data (JSON)
    verification_summary: Optional[json] = None  # Verification summary (JSON)
    status: Optional[str] = None  # Status of the critique

# Represents an audit log entry
@dataclass
class AuditLog:
    id: int  # Log entry ID
    log: Optional[str] = None  # Log message
    user: Optional[User] = None  # Reference to the User

# Stores feedback for a query
@dataclass
class Feedback:
    query_id: int  # Associated query ID
    id: Optional[int] = None  # Feedback ID
    feedback_tags: List[str] = field(default_factory=list)  # List of feedback tags
    comments: Optional[str] = None  # Additional comments
    timestamp: Optional[datetime] = field(default_factory=datetime.now)  # Feedback timestamp

# Stores groundedness evaluation for a query
@dataclass
class GroundednessEvaluation:
    id: Optional[int] = None  # Surrogate PK
    query_id: Optional[int] = None  # FK to queries.query_id
    timestamp: Optional[datetime] = field(default_factory=datetime.now)  # evaluation timestamp (no TZ in your schema)
    answer: Optional[str] = None  # Model answer
    context_snippet: Optional[str] = None  # Context provided to the model
    grounded: bool = False  # Whether answer is grounded
    score: Optional[Decimal] = None  # Groundedness score [0,1]
    confidence: Optional[Decimal] = None  # Confidence [0,1]
    failure_mode: Optional[str] = None  # Failure mode label/category
    unsupported_claims: Optional[json] = None  # JSONB
    recommendations: Optional[json] = None  # JSONB
    intent_fulfillment: Optional[bool] = None  # Whether intent was fulfilled
    intent_gaps: Optional[json] = None  # JSONB
    evaluation_summary: Optional[str] = None  # Free-text summary
    citation_audit: Optional[json] = None  # JSONB
    policies_applied: Optional[json] = None  # JSONB
    latency_ms: Optional[int] = None  # Eval latency in ms
    model: Optional[str] = None  # Model identifier
    query: Optional['Queries'] = None  # Relationship to Queries (if you expose it)
