#app/persistence/orm.py
import threading

#=====================================================================================================#
#Copyright (c) 2026 Agilent Technologies All rights reserved worldwide.
#Agilent Confidential, Use is permitted only in accordance with applicable End User License Agreement.
#=====================================================================================================#

from sqlalchemy import Column, ForeignKey, Integer, MetaData, create_engine, DateTime, DECIMAL, func, ARRAY, inspect, \
    Numeric
from sqlalchemy import Table, String, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.orm import sessionmaker, registry, relationship, clear_mappers

from app.models.models import User, UserDetails, UserSessions, Queries, OpenAIUsage, QueryDetails, AuditLog, Feedback, \
    SelfCritiqueMetrics, GroundednessEvaluation


class Engine:
    """
    Handles SQLAlchemy engine, session, and ORM mappings for all models.
    """
    _mappers_initialized = False
    _mappers_lock = threading.Lock()

    def __init__(self, hostname, port, username, password, database, schema_name="public", ssl_mode="disable",
                 **pool_kwargs):
        """
        Initializes the Engine and creates a new database session.
        """
        self.__engine = None
        self.__registry = None
        self.session = None
        self.create_new_session(hostname, port, username, password, database, schema_name, ssl_mode, **pool_kwargs)

    def create_new_session(self, hostname, port, username, password, database, schema_name="public", ssl_mode="disable",
                           **pool_kwargs):
        """
        Creates a new SQLAlchemy engine and session, and sets up ORM mappings.
        """
        if self.__engine:
            self.__engine.dispose()
            self.__registry.dispose()
            clear_mappers()

        # Pass pool arguments to create_engine
        self.__engine = create_engine(
            f"postgresql+psycopg2://{username}:{password}@{hostname}:{port}/{database}?sslmode={ssl_mode}",
            **pool_kwargs
        )
        self.__metadata = MetaData(schema=schema_name)
        self.session = sessionmaker(autocommit=False, autoflush=False, bind=self.__engine)()
        self.__registry = registry()
        self.__run_mappers()

    @property
    def engine(self):
        return self.__engine

    def __run_mappers(self):
        """
        Maps Python classes to database tables using SQLAlchemy's ORM.
        Ensures mapping is done only once, even with concurrent access.
        """
        if not self._mappers_initialized:
            with self._mappers_lock:
                if not self._mappers_initialized:
                    self._mappers_initialized = True
                    self.__map_all_models()


    def __map_all_models(self):
        """
        Maps all data models to their corresponding database tables.
        """
        # User table mapping
        #check mapping before running this
        try:
            inspect(User)
        except NoInspectionAvailable:
            user_table = Table(
                'user',
                self.__metadata,
                Column('user_id', Integer, primary_key=True, autoincrement=True),
                Column('ad_user_id', String),
                Column('ad_user_id_hash', String)  # Add hash column for deterministic lookup
            )
            self.__registry.map_imperatively(
                User,
                user_table,
                properties={
                    "_ad_user_id": user_table.c.ad_user_id,  # Map DB column to _ad_user_id
                    "details": relationship(UserDetails, backref="User", cascade="all, delete-orphan", uselist=False)
                }
            )

        # UserDetails table mapping
        try:
            inspect(UserDetails)
        except NoInspectionAvailable:
            user_details_table = Table(
                'user_details',
                self.__metadata,
                Column('user_id', Integer, ForeignKey('user.user_id'), primary_key=True),
                Column('user_name', String),
                Column('user_email', String),
                Column('location', String),
                Column('department', String),
                Column('role', String)
            )
            self.__registry.map_imperatively(
                UserDetails,
                user_details_table,
                properties={
                    "_user_name": user_details_table.c.user_name,
                    "_user_email": user_details_table.c.user_email,
                    "_location": user_details_table.c.location,
                    "_department": user_details_table.c.department,
                    "_role": user_details_table.c.role,
                }
            )
        # UserSessions table mapping
        try:
            inspect(UserSessions)
        except NoInspectionAvailable:
            self.__registry.map_imperatively(
                UserSessions,
                Table(
                    'user_sessions',
                    self.__metadata,
                    Column('id', Integer, primary_key=True, autoincrement=True),
                    Column('session_id', String),
                    Column('user_id', Integer, ForeignKey('user.user_id')),
                    Column('session_start_timestamp', DateTime),
                    Column('session_end_timestamp', DateTime)
                ),
            )
        # Queries table mapping
        try:
            inspect(Queries)
        except NoInspectionAvailable:
            self.__registry.map_imperatively(
                Queries,
                Table(
                    'queries',
                    self.__metadata,
                    Column('query_id', Integer, primary_key=True, autoincrement=True),
                    Column('session_id', Integer, ForeignKey('user_sessions.id')),
                    Column('timestamp', DateTime, nullable=False, server_default=func.now()),
                ),
                properties = {
                    "details": relationship(QueryDetails, backref="Queries", cascade="all, delete-orphan", uselist=False)
                }
            )

        # QueryDetails table mapping
        try:
            inspect(QueryDetails)
        except NoInspectionAvailable:
            self.__registry.map_imperatively(
                QueryDetails,
                Table(
                    'query_details',
                    self.__metadata,
                    Column('query_id', Integer, ForeignKey('queries.query_id'), primary_key=True),
                    Column('user_query', String),
                    Column('response', String),
                    Column('latency_ms', Integer),
                    Column('is_follow_up', Boolean),
                    Column('mode', String),
                    Column('persona', String),
                    Column('llm_latency_ms', Integer),
                    Column('reranker_latency_ms', Integer),
                    Column('search_latency_ms', Integer),
                    Column('sources', JSONB),
                    Column('features_json', JSONB)
                ),
                properties={
                    "self_critique_metrics": relationship(SelfCritiqueMetrics, backref="QueryDetails", cascade="all, delete-orphan", uselist=False)
                }
            )

        # SelfCritiqueMetrics table mapping
        try:
            inspect(SelfCritiqueMetrics)
        except NoInspectionAvailable:
            self.__registry.map_imperatively(
                SelfCritiqueMetrics,
                Table(
                    'self_critique_metrics',
                    self.__metadata,
                    Column('query_id', Integer, ForeignKey('query_details.query_id'),primary_key=True),
                    Column('refined_response', String),
                    Column('critique_json', JSONB),
                    Column('verification_summary', JSONB),
                    Column('status', String)
                )
            )

        # OpenAIUsage table mapping
        try:
            inspect(OpenAIUsage)
        except NoInspectionAvailable:
            self.__registry.map_imperatively(
                OpenAIUsage,
                Table(
                    'openai_usage_new',
                    self.__metadata,
                    Column('id', Integer, primary_key=True, autoincrement=True),
                    Column('timestamp',DateTime, nullable=False, server_default=func.now()),
                    Column('model', String),
                    Column('call_type', String),
                    Column('prompt_tokens', Integer),
                    Column('completion_tokens', Integer),
                    Column('total_tokens', Integer),
                    Column('query_id', Integer, ForeignKey('queries.query_id')),
                    Column('user_id', Integer, ForeignKey('user_details.user_id')),
                    Column('scenario', String),
                    Column('prompt_cost', DECIMAL),
                    Column('completion_cost', DECIMAL),
                    Column('total_cost', DECIMAL),
                ),
            )

        # AuditLog table mapping
        try:
            inspect(AuditLog)
        except NoInspectionAvailable:
            self.__registry.map_imperatively(
                AuditLog,
                Table(
                    'audit_log',
                    self.__metadata,
                    Column('id', Integer, primary_key=True),
                    Column('user_id', Integer, ForeignKey('user.id')),
                    Column('log', String)
                )
            )

        # Feedback table mapping
        try:
            inspect(Feedback)
        except NoInspectionAvailable:
            self.__registry.map_imperatively(
                Feedback,
                Table(
                    'feedback',
                    self.__metadata,
                    Column('id', Integer, primary_key=True, autoincrement=True),
                    Column('query_id', Integer, ForeignKey('queries.query_id')),
                    Column('feedback_tags', ARRAY(String)),
                    Column('comments', String),
                    Column('timestamp', DateTime, default=func.now())
                )
            )

        # Groundness Evaluation
        try:
            inspect(GroundednessEvaluation)
        except NoInspectionAvailable:
            self.__registry.map_imperatively(
                GroundednessEvaluation,
                Table(
                    'groundedness_evaluations',
                    self.__metadata,
                    Column('id', Integer, primary_key=True, autoincrement=True),
                    Column('query_id', Integer, ForeignKey('queries.query_id'), nullable=False),
                    Column('timestamp', DateTime, nullable=False, server_default=func.now()),
                    Column('answer', String),
                    Column('context_snippet', String),
                    Column('grounded', Boolean),
                    Column('score', Numeric(4, 3)),
                    Column('confidence', Numeric(4, 3)),
                    Column('failure_mode', String),
                    Column('unsupported_claims', JSONB),
                    Column('recommendations', JSONB),
                    Column('intent_fulfillment', Boolean),
                    Column('intent_gaps', JSONB),
                    Column('evaluation_summary', String),
                    Column('citation_audit', JSONB),
                    Column('policies_applied', JSONB),
                    Column('latency_ms', Integer),
                    Column('model', String),
                )
            )

